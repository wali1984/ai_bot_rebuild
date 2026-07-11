from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict, List, Mapping

from ...domain.symbols.models import SymbolIdentity
from ...domain.symbols.normalization import normalize_source_symbol
from ...services.binance_unified_websocket_transport import (
    REST_FALLBACK_ENV,
    binance_rest_fallback_allowed,
    require_binance_rest_fallback,
)


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


def _connect_redis() -> Any | None:
    try:
        import redis  # type: ignore

        client = redis.Redis.from_url(
            os.environ.get("V2_REDIS_URL") or os.environ.get("REDIS_URL") or "redis://127.0.0.1:6379/0",
            decode_responses=True,
            socket_timeout=1.0,
        )
        client.ping()
        return client
    except Exception:
        return None


def _redis_get_json(redis_client: Any, key: str) -> Any:
    if redis_client is None:
        return None
    try:
        return _read_json_value(redis_client.get(key))
    except Exception:
        return None


def _payload_has_symbols(payload: Any) -> bool:
    return isinstance(payload, Mapping) and isinstance(payload.get("symbols"), list)


class BinanceCoinMFuturesSource:
    source = "binance_coinm"

    def __init__(self, base_endpoint: str = "https://dapi.binance.com", redis_client: Any | None = None) -> None:
        self.base_endpoint = base_endpoint.rstrip("/")
        self.redis_client = redis_client

    @property
    def exchange_info_url(self) -> str:
        return f"{self.base_endpoint}/dapi/v1/exchangeInfo"

    def _fetch_exchange_info_from_cache(self) -> Dict[str, Any] | None:
        redis_client = self.redis_client if self.redis_client is not None else _connect_redis()
        for key in (
            "v2:exchange:binance_coinm:exchangeInfo",
            "v2:exchange:binance:coinm:exchangeInfo",
            "v2:exchange:coinm:exchangeInfo",
        ):
            payload = _redis_get_json(redis_client, key)
            if _payload_has_symbols(payload):
                return {
                    **dict(payload),
                    "source": str(payload.get("source") or "binance_coinm_websocket_cache_primary"),
                    "transport": "websocket_cache_primary",
                    "source_key": key,
                    "rest_fallback_used": False,
                }
        return None

    def fetch_exchange_info(self, timeout: float = 10.0) -> Dict[str, Any]:
        cached = self._fetch_exchange_info_from_cache()
        if cached is not None:
            return cached
        try:
            require_binance_rest_fallback(
                endpoint="/dapi/v1/exchangeInfo",
                fallback_reason="binance_coinm_symbol_source_cache_missing",
                role="symbol_source_exchange_info_recovery",
            )
        except RuntimeError as exc:
            message = str(exc).replace(
                "REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
                "BINANCE_REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
                1,
            )
            raise RuntimeError(message) from exc
        with urllib.request.urlopen(self.exchange_info_url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, dict):
            payload["source"] = "binance_coinm_exchangeInfo_rest_fallback"
            payload["transport"] = "rest_fallback"
            payload["rest_fallback_used"] = True
        return payload

    def from_payload(self, payload: Dict[str, Any]) -> List[SymbolIdentity]:
        return [normalize_source_symbol(self.source, item) for item in payload.get("symbols", [])]
