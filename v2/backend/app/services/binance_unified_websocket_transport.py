"""Unified Binance USD-M WebSocket transport policy and credential binding.

The functions in this module centralize Binance credential selection and
WebSocket API request construction. They never log or return raw credential
values from public status helpers. Exchange mutation is still controlled by the
caller's live gates; this module only knows how to build/send a gated request.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
    closed_candle_key,
    current_candle_key,
    parse_ms,
)
from v2.backend.app.services.runtime_clock import (
    age_seconds_from_epoch_ms,
    epoch_ms_now,
    epoch_ms_to_est_iso,
    est_now_iso,
)

DEFAULT_TRADER_ID = "trader-wajidali1984"
DEFAULT_CREDENTIAL_REF = "ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY"

BINANCE_USDM_WS_API_URL = "wss://ws-fapi.binance.com/ws-fapi/v1"
BINANCE_USDM_TESTNET_WS_API_URL = "wss://testnet.binancefuture.com/ws-fapi/v1"
BINANCE_USDM_MARKET_STREAM_URL = "wss://fstream.binance.com"
BINANCE_USDM_REST_BASE_URL = "https://fapi.binance.com"

_WS_API_URL_ENV = "V2_BINANCE_USDM_WS_API_URL"
_WS_API_TESTNET_ENV = "BINANCE_TESTNET"
_INITIAL_TRADER_ID_ENV = "ALPHAFORGE_INITIAL_TRADER_ID"
_INITIAL_CREDENTIAL_REF_ENV = "ALPHAFORGE_INITIAL_TRADER_BINANCE_CREDENTIAL_REF"

_SECRET_FIELD_TOKENS = ("key", "secret", "signature")


@dataclass(frozen=True)
class BinanceCredentialBinding:
    trader_id: str
    credential_ref: str
    api_key: str
    api_secret: str
    api_key_name: str | None
    api_secret_name: str | None
    api_key_source: str | None
    api_secret_source: str | None
    account_specific: bool
    read_only_ref: bool

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def safe_status(self) -> dict[str, Any]:
        return {
            "trader_id": self.trader_id,
            "credential_ref": self.credential_ref,
            "credential_scope": "trader_scoped_binance_env",
            "account_specific": self.account_specific,
            "default_trader_binding": (
                self.trader_id == DEFAULT_TRADER_ID
                and self.credential_ref == DEFAULT_CREDENTIAL_REF
            ),
            "generic_binance_env_fallback_used": self.is_configured and not self.account_specific,
            "strict_account_specific_env_present": self.is_configured and self.account_specific,
            "read_only_ref": self.read_only_ref,
            "configured": self.is_configured,
            "api_key_present": bool(self.api_key),
            "api_secret_present": bool(self.api_secret),
            "key_names_used": {
                "api_key": self.api_key_name,
                "api_secret": self.api_secret_name,
            },
            "key_sources": {
                "api_key": self.api_key_source,
                "api_secret": self.api_secret_source,
            },
            "raw_credential_in_payload": "NEVER",
            "raw_credentials_exposed": False,
        }


def repo_root_from(path: Path | None = None) -> Path:
    if path is not None:
        return path.resolve()
    return Path(os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD")).resolve()


def binance_ws_api_url() -> str:
    configured = os.environ.get(_WS_API_URL_ENV, "").strip()
    if configured:
        return configured.rstrip("/")
    if os.environ.get(_WS_API_TESTNET_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
        return BINANCE_USDM_TESTNET_WS_API_URL
    return BINANCE_USDM_WS_API_URL


def transport_policy_snapshot() -> dict[str, Any]:
    return {
        "schema_version": "binance_unified_websocket_transport_policy_v1",
        "market_data_primary": "binance_usdm_public_websocket_stream",
        "market_data_base_url": BINANCE_USDM_MARKET_STREAM_URL,
        "trading_private_primary": "binance_usdm_websocket_api",
        "trading_websocket_api_url": binance_ws_api_url(),
        "signed_account_read_primary_methods": ["account.status", "account.position"],
        "order_place_method": "order.place",
        "cancel_modify_methods_available_but_disabled": ["order.cancel", "order.modify"],
        "cancel_modify_enabled": False,
        "test_order_enabled": False,
        "leverage_margin_mutation_enabled": False,
        "rest_fallback_enabled_for_order_submit": False,
        "public_market_data_rest_backup": "enabled_only_when_wss_cache_missing_or_stale",
        "public_symbol_metadata_rest_fallback": "exchangeInfo_only",
        "official_github_sdk_package": "binance-sdk-derivatives-trading-usds-futures",
        "operator_time_zone": "America/New_York",
        "protocol_timestamp_ms_internal": True,
        "raw_credentials_exposed": False,
    }


@dataclass(frozen=True)
class UnifiedMarketDataSnapshot:
    symbol: str
    timeframe: str
    price: float | None
    source_type: str
    source: str
    source_pointer: str
    generated_at: str
    generated_est: str
    last_event_at: str | None
    last_event_est: str | None
    last_event_ms: int | None
    age_seconds: int | None
    freshness_state: str
    errors: list[str]
    candles: list[dict[str, Any]]
    wss_cache_used: bool
    wss_cache_reason: str
    rest_backup_used: bool
    rest_backup_reason: str | None
    cache_backup_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "price": self.price,
            "source_type": self.source_type,
            "source": self.source,
            "source_pointer": self.source_pointer,
            "generated_at": self.generated_at,
            "generated_est": self.generated_est,
            "last_event_at": self.last_event_at,
            "last_event_est": self.last_event_est,
            "last_event_ms": self.last_event_ms,
            "age_seconds": self.age_seconds,
            "freshness_state": self.freshness_state,
            "errors": list(self.errors),
            "candles": list(self.candles),
            "wss_cache_used": self.wss_cache_used,
            "wss_cache_reason": self.wss_cache_reason,
            "rest_backup_used": self.rest_backup_used,
            "rest_backup_reason": self.rest_backup_reason,
            "cache_backup_used": self.cache_backup_used,
            "operator_time_zone": "America/New_York",
        }


def _freshness(age_seconds: int | None) -> str:
    if age_seconds is None:
        return "MISSING"
    if age_seconds <= 120:
        return "CURRENT"
    if age_seconds <= 300:
        return "WARN"
    return "STALE"


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _is_wss_candle(row: Mapping[str, Any]) -> bool:
    return str(row.get("source") or "").lower() == "binance_wss"


def _is_closed_candle(row: Mapping[str, Any]) -> bool:
    return (
        row.get("is_closed") is True
        or row.get("closed_candle") is True
        or row.get("candle_closed_confirmed") is True
    )


def _ohlcv(row: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = row.get("ohlcv")
    return nested if isinstance(nested, Mapping) else {}


def _default_public_rest_get_json(
    path: str,
    params: Mapping[str, str],
    *,
    timeout: float = 8.0,
) -> Any:
    url = f"{BINANCE_USDM_REST_BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(  # noqa: S310 - fixed Binance HTTPS base URL.
        url,
        method="GET",
        headers={"User-Agent": "ai-bot-v2-binance-unified-readonly"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


class BinanceUnifiedMarketDataClient:
    """Read-only Binance market-data facade.

    Public WSS Redis cache is primary. Public REST is only used as an explicit
    backup when that cache is unavailable, non-WSS, or stale.
    """

    def __init__(
        self,
        *,
        redis_client: Any | None = None,
        rest_get_json: Callable[[str, Mapping[str, str]], Any] | None = None,
        clock_ms: Callable[[], int] | None = None,
        max_wss_cache_age_seconds: int = 120,
    ) -> None:
        self.redis_client = redis_client if redis_client is not None else self._connect_redis()
        self.rest_get_json = rest_get_json or (
            lambda path, params: _default_public_rest_get_json(path, params)
        )
        self.clock_ms = clock_ms or epoch_ms_now
        self.max_wss_cache_age_seconds = int(max_wss_cache_age_seconds)

    @staticmethod
    def _connect_redis() -> Any | None:
        try:
            import redis  # type: ignore

            url = os.getenv("V2_REDIS_URL") or os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/0"
            client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=1.0)
            client.ping()
            return client
        except Exception:
            return None

    def fetch_snapshot(
        self,
        symbol: str,
        *,
        timeframe: str = "1m",
        limit: int = 30,
    ) -> UnifiedMarketDataSnapshot:
        normalized_symbol = str(symbol).strip().upper()
        normalized_timeframe = str(timeframe).strip() or "1m"
        snapshot, wss_reason = self._from_wss_cache(
            normalized_symbol,
            normalized_timeframe,
            limit=limit,
        )
        if snapshot is not None:
            return snapshot
        snapshot = self._from_non_wss_cache_backup(
            normalized_symbol,
            normalized_timeframe,
            limit=limit,
            wss_reason=wss_reason,
        )
        if snapshot is not None:
            return snapshot
        return self._from_rest_backup(
            normalized_symbol,
            normalized_timeframe,
            limit=limit,
            wss_reason=wss_reason,
        )

    def _redis_get_json(self, key: str) -> tuple[Any, str | None]:
        if self.redis_client is None:
            return None, "REDIS_CLIENT_MISSING"
        try:
            return _read_json_value(self.redis_client.get(key)), None
        except Exception as exc:
            return None, f"REDIS_READ_FAILED:{type(exc).__name__}"

    def _format_candle(self, row: Mapping[str, Any]) -> dict[str, Any]:
        ohlcv = row.get("ohlcv") if isinstance(row.get("ohlcv"), Mapping) else {}
        open_ms = parse_ms(row.get("candle_open_time") or row.get("open_time") or row.get("ts"))
        close_ms = parse_ms(row.get("candle_close_time") or row.get("close_time"))
        event_ms = parse_ms(row.get("event_time"))
        available_ms = parse_ms(row.get("available_at"))
        return {
            "time": epoch_ms_to_est_iso(open_ms),
            "open_time_ms": open_ms,
            "close_time_ms": close_ms,
            "event_time_ms": event_ms,
            "available_at_ms": available_ms,
            "open": _float_or_none(row.get("open") or ohlcv.get("open")),
            "high": _float_or_none(row.get("high") or ohlcv.get("high")),
            "low": _float_or_none(row.get("low") or ohlcv.get("low")),
            "close": _float_or_none(row.get("close") or ohlcv.get("close")),
            "volume": _float_or_none(row.get("volume") or ohlcv.get("volume")),
            "source": row.get("source"),
            "source_type": "READONLY_MARKET_FEED",
        }

    def _from_wss_cache(
        self,
        symbol: str,
        timeframe: str,
        *,
        limit: int,
    ) -> tuple[UnifiedMarketDataSnapshot | None, str]:
        current_key = current_candle_key("binance", symbol, timeframe)
        closed_key = closed_candle_key("binance", symbol, timeframe)
        current_raw, current_error = self._redis_get_json(current_key)
        closed_raw, closed_error = self._redis_get_json(closed_key)
        if current_error and closed_error and current_error == closed_error:
            return None, current_error
        if current_error and closed_error:
            return None, f"{current_error};{closed_error}"

        current = current_raw if isinstance(current_raw, Mapping) else None
        closed_rows = [dict(row) for row in closed_raw] if isinstance(closed_raw, list) else []
        wss_closed = [
            row
            for row in closed_rows
            if isinstance(row, Mapping)
            and _is_wss_candle(row)
            and _is_closed_candle(row)
            and (parse_ms(row.get("available_at")) or 0) <= self.clock_ms()
        ]
        wss_current = current if isinstance(current, Mapping) and _is_wss_candle(current) else None
        if not wss_current and not wss_closed:
            sources = {
                str(row.get("source") or "missing")
                for row in ([current] if current else []) + closed_rows[-3:]
                if isinstance(row, Mapping)
            }
            reason = (
                "WSS_CACHE_MISSING"
                if not sources
                else f"WSS_CACHE_SOURCE_NOT_WSS:{','.join(sorted(sources))}"
            )
            return None, reason

        event_ms = None
        price = None
        if wss_current:
            event_ms = parse_ms(wss_current.get("event_time") or wss_current.get("close_time"))
            price = _float_or_none(wss_current.get("close") or _ohlcv(wss_current).get("close"))
        if event_ms is None and wss_closed:
            latest = max(
                wss_closed,
                key=lambda row: int(
                    parse_ms(row.get("candle_close_time") or row.get("close_time")) or 0
                ),
            )
            event_ms = parse_ms(
                latest.get("event_time")
                or latest.get("candle_close_time")
                or latest.get("close_time")
            )
            price = _float_or_none(latest.get("close") or _ohlcv(latest).get("close"))
        age_seconds = age_seconds_from_epoch_ms(event_ms, now_ms=self.clock_ms())
        if age_seconds is None:
            return None, "WSS_CACHE_EVENT_TIME_MISSING"
        if age_seconds > self.max_wss_cache_age_seconds:
            return None, f"WSS_CACHE_STALE:{age_seconds}s"

        wss_closed.sort(
            key=lambda row: int(
                parse_ms(row.get("candle_open_time") or row.get("open_time") or 0) or 0
            )
        )
        candles = [self._format_candle(row) for row in wss_closed[-max(1, int(limit)) :]]
        generated = est_now_iso()
        event_est = epoch_ms_to_est_iso(event_ms)
        return (
            UnifiedMarketDataSnapshot(
                symbol=symbol,
                timeframe=timeframe,
                price=price,
                source_type="READONLY_MARKET_FEED",
                source="binance_usdm_wss_cache_primary",
                source_pointer=f"{current_key} + {closed_key}",
                generated_at=generated,
                generated_est=generated,
                last_event_at=event_est,
                last_event_est=event_est,
                last_event_ms=event_ms,
                age_seconds=age_seconds,
                freshness_state=_freshness(age_seconds),
                errors=[],
                candles=candles,
                wss_cache_used=True,
                wss_cache_reason="WSS_CACHE_CURRENT",
                rest_backup_used=False,
                rest_backup_reason=None,
            ),
            "WSS_CACHE_CURRENT",
        )

    def _from_non_wss_cache_backup(
        self,
        symbol: str,
        timeframe: str,
        *,
        limit: int,
        wss_reason: str,
    ) -> UnifiedMarketDataSnapshot | None:
        current_key = current_candle_key("binance", symbol, timeframe)
        closed_key = closed_candle_key("binance", symbol, timeframe)
        current_raw, _current_error = self._redis_get_json(current_key)
        closed_raw, _closed_error = self._redis_get_json(closed_key)
        current = current_raw if isinstance(current_raw, Mapping) else None
        closed_rows = [dict(row) for row in closed_raw] if isinstance(closed_raw, list) else []
        now_ms = self.clock_ms()
        usable_closed = [
            row
            for row in closed_rows
            if isinstance(row, Mapping)
            and _is_closed_candle(row)
            and (parse_ms(row.get("available_at")) or 0) <= now_ms
        ]
        if not usable_closed:
            return None

        event_ms = None
        price = None
        if current:
            event_ms = parse_ms(
                current.get("event_time")
                or current.get("close_time")
                or current.get("candle_close_time")
            )
            price = _float_or_none(current.get("close") or _ohlcv(current).get("close"))
        if event_ms is None:
            latest = max(
                usable_closed,
                key=lambda row: int(
                    parse_ms(row.get("candle_close_time") or row.get("close_time")) or 0
                ),
            )
            event_ms = parse_ms(
                latest.get("event_time")
                or latest.get("candle_close_time")
                or latest.get("close_time")
            )
            price = _float_or_none(latest.get("close") or _ohlcv(latest).get("close"))

        age_seconds = age_seconds_from_epoch_ms(event_ms, now_ms=now_ms)
        if age_seconds is None or age_seconds > self.max_wss_cache_age_seconds:
            return None

        usable_closed.sort(
            key=lambda row: int(
                parse_ms(row.get("candle_open_time") or row.get("open_time") or 0) or 0
            )
        )
        sources = {
            str(row.get("source") or "missing")
            for row in ([current] if current else []) + usable_closed[-3:]
            if isinstance(row, Mapping)
        }
        generated = est_now_iso()
        event_est = epoch_ms_to_est_iso(event_ms)
        return UnifiedMarketDataSnapshot(
            symbol=symbol,
            timeframe=timeframe,
            price=price,
            source_type="READONLY_MARKET_FEED",
            source="binance_redis_market_cache_backup",
            source_pointer=f"{current_key} + {closed_key}",
            generated_at=generated,
            generated_est=generated,
            last_event_at=event_est,
            last_event_est=event_est,
            last_event_ms=event_ms,
            age_seconds=age_seconds,
            freshness_state=_freshness(age_seconds),
            errors=[
                f"wss_primary_unavailable:{wss_reason}",
                f"cache_backup_sources:{','.join(sorted(sources))}",
            ],
            candles=[
                self._format_candle(row)
                for row in usable_closed[-max(1, int(limit)) :]
            ],
            wss_cache_used=False,
            wss_cache_reason=wss_reason,
            rest_backup_used=False,
            rest_backup_reason=None,
            cache_backup_used=True,
        )

    def _from_rest_backup(
        self,
        symbol: str,
        timeframe: str,
        *,
        limit: int,
        wss_reason: str,
    ) -> UnifiedMarketDataSnapshot:
        generated = est_now_iso()
        errors = [f"wss_primary_unavailable:{wss_reason}"]
        try:
            ticker = self.rest_get_json("/fapi/v1/ticker/price", {"symbol": symbol})
            raw_klines = self.rest_get_json(
                "/fapi/v1/klines",
                {"symbol": symbol, "interval": timeframe, "limit": str(max(1, int(limit)))},
            )
            if not isinstance(raw_klines, list):
                raise TypeError("binance_rest_klines_not_list")
            now_ms = self.clock_ms()
            candles_raw = [
                canonical_from_binance_rest(
                    row,
                    symbol=symbol,
                    timeframe=timeframe,
                    ingested_at=now_ms,
                ).to_dict()
                for row in raw_klines
                if isinstance(row, list | tuple)
            ]
            candles_raw = [
                row
                for row in candles_raw
                if _is_closed_candle(row) and (parse_ms(row.get("available_at")) or 0) <= now_ms
            ]
            event_ms = parse_ms(ticker.get("time") if isinstance(ticker, Mapping) else None)
            if event_ms is None and candles_raw:
                event_ms = parse_ms(
                    candles_raw[-1].get("candle_close_time") or candles_raw[-1].get("close_time")
                )
            price = _float_or_none(ticker.get("price") if isinstance(ticker, Mapping) else None)
            if price is None and candles_raw:
                price = _float_or_none(candles_raw[-1].get("close"))
            age_seconds = age_seconds_from_epoch_ms(event_ms, now_ms=now_ms)
            event_est = epoch_ms_to_est_iso(event_ms)
            return UnifiedMarketDataSnapshot(
                symbol=symbol,
                timeframe=timeframe,
                price=price,
                source_type="READONLY_MARKET_FEED" if price is not None else "MISSING_EVIDENCE",
                source="binance_usdm_rest_backup",
                source_pointer="/fapi/v1/ticker/price + /fapi/v1/klines",
                generated_at=generated,
                generated_est=generated,
                last_event_at=event_est,
                last_event_est=event_est,
                last_event_ms=event_ms,
                age_seconds=age_seconds,
                freshness_state=_freshness(age_seconds),
                errors=errors,
                candles=[
                    self._format_candle(row)
                    for row in candles_raw[-max(1, int(limit)) :]
                ],
                wss_cache_used=False,
                wss_cache_reason=wss_reason,
                rest_backup_used=True,
                rest_backup_reason=wss_reason,
            )
        except (
            OSError,
            urllib.error.URLError,
            TimeoutError,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
        ) as exc:
            errors.append(f"binance_usdm_rest_backup_failed:{type(exc).__name__}")
            return UnifiedMarketDataSnapshot(
                symbol=symbol,
                timeframe=timeframe,
                price=None,
                source_type="MISSING_EVIDENCE",
                source="binance_unified_wss_primary_rest_backup",
                source_pointer="/fapi/v1/ticker/price + /fapi/v1/klines",
                generated_at=generated,
                generated_est=generated,
                last_event_at=None,
                last_event_est=None,
                last_event_ms=None,
                age_seconds=None,
                freshness_state="MISSING",
                errors=errors,
                candles=[],
                wss_cache_used=False,
                wss_cache_reason=wss_reason,
                rest_backup_used=True,
                rest_backup_reason=wss_reason,
            )


def fetch_unified_market_snapshot(
    symbol: str,
    *,
    timeframe: str = "1m",
    limit: int = 30,
) -> UnifiedMarketDataSnapshot:
    return BinanceUnifiedMarketDataClient().fetch_snapshot(symbol, timeframe=timeframe, limit=limit)


def _env_prefix(credential_ref: str) -> str:
    return re.sub(r"[^A-Z0-9_]", "_", credential_ref.upper()).strip("_")


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _credential_files(root: Path) -> tuple[Path, ...]:
    return (
        root / "v2/.env.local",
        root / ".local_secrets/live_credentials.env",
        root / ".local_secrets/legacy.env",
    )


def _resolve_name(
    name: str,
    file_values: Mapping[Path, Mapping[str, str]],
) -> tuple[str, str | None]:
    env_value = os.environ.get(name, "").strip()
    if env_value:
        return env_value, "os.environ"
    for path, values in file_values.items():
        value = values.get(name, "").strip()
        if value:
            return value, str(path)
    return "", None


def _candidate_pairs(credential_ref: str) -> list[tuple[str, str, bool]]:
    prefix = _env_prefix(credential_ref)
    return [
        (f"{prefix}_API_KEY", f"{prefix}_API_SECRET", True),
        (f"{prefix}_KEY", f"{prefix}_SECRET", True),
        ("BINANCE_API_KEY", "BINANCE_API_SECRET", False),
        ("BINANCE_FUT_API_KEY", "BINANCE_FUT_API_SECRET", False),
        ("BINANCE_API_KEY", "BINANCE_SECRET_KEY", False),
        ("BINANCE_LIVE_API_KEY", "BINANCE_LIVE_API_SECRET", False),
    ]


def resolve_binance_credential_binding(
    *,
    repo_root: Path | None = None,
    trader_id: str | None = None,
    credential_ref: str | None = None,
) -> BinanceCredentialBinding:
    root = repo_root_from(repo_root)
    file_values = {path: _parse_env_file(path) for path in _credential_files(root)}
    merged_for_config: dict[str, str] = {}
    for values in reversed(tuple(file_values.values())):
        merged_for_config.update(values)
    resolved_trader_id = (
        trader_id
        or os.environ.get(_INITIAL_TRADER_ID_ENV)
        or merged_for_config.get(_INITIAL_TRADER_ID_ENV)
        or DEFAULT_TRADER_ID
    ).strip()
    resolved_ref = (
        credential_ref
        or os.environ.get(_INITIAL_CREDENTIAL_REF_ENV)
        or merged_for_config.get(_INITIAL_CREDENTIAL_REF_ENV)
        or DEFAULT_CREDENTIAL_REF
    ).strip()
    for key_name, secret_name, account_specific in _candidate_pairs(resolved_ref):
        api_key, key_source = _resolve_name(key_name, file_values)
        api_secret, secret_source = _resolve_name(secret_name, file_values)
        if api_key and api_secret:
            return BinanceCredentialBinding(
                trader_id=resolved_trader_id,
                credential_ref=resolved_ref,
                api_key=api_key,
                api_secret=api_secret,
                api_key_name=key_name,
                api_secret_name=secret_name,
                api_key_source=key_source,
                api_secret_source=secret_source,
                account_specific=account_specific,
                read_only_ref="READONLY" in _env_prefix(resolved_ref).split("_"),
            )
    first_key_name, first_secret_name, account_specific = _candidate_pairs(resolved_ref)[0]
    return BinanceCredentialBinding(
        trader_id=resolved_trader_id,
        credential_ref=resolved_ref,
        api_key="",
        api_secret="",
        api_key_name=first_key_name,
        api_secret_name=first_secret_name,
        api_key_source=None,
        api_secret_source=None,
        account_specific=account_specific,
        read_only_ref="READONLY" in _env_prefix(resolved_ref).split("_"),
    )


def canonical_signature_payload(params: Mapping[str, Any]) -> str:
    filtered = {k: v for k, v in params.items() if k != "signature" and v is not None}
    return urllib.parse.urlencode(sorted(filtered.items()), doseq=True)


def sign_hmac_sha256(params: Mapping[str, Any], api_secret: str) -> str:
    payload = canonical_signature_payload(params)
    return hmac.new(api_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def build_signed_ws_api_request(
    *,
    method: str,
    params: Mapping[str, Any],
    api_key: str,
    api_secret: str,
    request_id: str | None = None,
    clock_ms: Callable[[], int] | None = None,
) -> dict[str, Any]:
    now_ms = int((clock_ms or (lambda: int(time.time() * 1000)))())
    signed_params = {k: v for k, v in params.items() if v is not None}
    signed_params["apiKey"] = api_key
    signed_params["timestamp"] = int(signed_params.get("timestamp") or now_ms)
    signed_params["signature"] = sign_hmac_sha256(signed_params, api_secret)
    return {
        "id": request_id or str(uuid4()),
        "method": method,
        "params": signed_params,
    }


def redact_ws_api_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    def redact(value: Any) -> Any:
        if isinstance(value, Mapping):
            out: dict[str, Any] = {}
            for key, item in value.items():
                if any(token in str(key).lower() for token in _SECRET_FIELD_TOKENS):
                    out[str(key)] = "[redacted]"
                else:
                    out[str(key)] = redact(item)
            return out
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    return redact(payload)


def redacted_json(payload: Any, *, limit: int = 2000) -> str:
    try:
        redacted = redact_ws_api_payload(payload) if isinstance(payload, Mapping) else payload
        return json.dumps(redacted, sort_keys=True, default=str)[:limit]
    except Exception:
        return ""


def default_ws_api_sender(
    *,
    endpoint: str,
    payload: Mapping[str, Any],
    timeout: float = 8.0,
) -> dict[str, Any]:
    try:
        from websockets.sync.client import connect  # type: ignore
    except Exception as exc:
        return {
            "ok": False,
            "status_code": None,
            "error_type": type(exc).__name__,
            "response": None,
        }
    try:
        with connect(endpoint, open_timeout=timeout, close_timeout=timeout) as websocket:
            websocket.send(json.dumps(payload, separators=(",", ":"), default=str))
            raw = websocket.recv(timeout=timeout)
    except Exception as exc:
        return {
            "ok": False,
            "status_code": None,
            "error_type": type(exc).__name__,
            "response": None,
        }
    try:
        response = json.loads(raw) if isinstance(raw, str) else {}
    except Exception:
        response = {"raw": str(raw)[:1000]}
    return {
        "ok": isinstance(response, dict) and int(response.get("status") or 0) == 200,
        "status_code": int(response.get("status") or 0) if isinstance(response, dict) else None,
        "error_type": None,
        "response": response,
    }
