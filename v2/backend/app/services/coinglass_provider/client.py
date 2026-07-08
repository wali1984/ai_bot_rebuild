"""Read-only CoinGlass HTTP client."""

from __future__ import annotations

import hashlib
import os
from typing import Any, Mapping

import httpx

from v2.backend.app.services.coinglass_provider.endpoint_registry import CoinGlassEndpointSpec
from v2.backend.app.services.coinglass_provider.models import CoinGlassResponse
from v2.backend.app.services.coinglass_provider.rate_limit import (
    COINGLASS_TIMEOUT_SECONDS,
    CoinGlassRateLimiter,
)


DEFAULT_BASE_URL = "https://open-api-v4.coinglass.com"


def key_hash_prefix(api_key: str | None) -> str | None:
    if not api_key:
        return None
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:8]


class CoinGlassClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        limiter: CoinGlassRateLimiter | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("COINGLASS_API_KEY")
        self.base_url = (base_url or os.getenv("COINGLASS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.limiter = limiter or CoinGlassRateLimiter()
        self.http_client = http_client

    @property
    def api_key_present(self) -> bool:
        return bool(str(self.api_key or "").strip())

    def get(
        self,
        spec: CoinGlassEndpointSpec,
        *,
        symbol: str | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> CoinGlassResponse:
        if not self.api_key_present:
            return CoinGlassResponse(spec.endpoint_id, symbol, 401, None, error_class="API_KEY_MISSING")
        allowed, reason = self.limiter.allow_request()
        if not allowed:
            return CoinGlassResponse(spec.endpoint_id, symbol, None, None, error_class=reason)
        merged = dict(getattr(spec, "default_params", ()) or ())
        merged.update(params or {})
        if symbol and "symbol" not in merged:
            merged["symbol"] = (
                str(symbol).upper()
                if getattr(spec, "symbol_format", "coin") == "pair"
                else _coin(symbol)
            )
        try:
            close_client = self.http_client is None
            client = self.http_client or httpx.Client(timeout=COINGLASS_TIMEOUT_SECONDS)
            try:
                response = client.get(
                    f"{self.base_url}{spec.path}",
                    params=merged,
                    headers={"CG-API-KEY": str(self.api_key), "accept": "application/json"},
                )
            finally:
                if close_client:
                    client.close()
            payload = _safe_json(response)
            headers = dict(response.headers)
            # CoinGlass signals plan/auth problems INSIDE a 200 body:
            # {"code": "401", "msg": "Upgrade plan", "success": false}.
            body_code = str(payload.get("code")) if isinstance(payload, dict) else "0"
            if response.status_code == 200 and body_code not in ("0", "None"):
                plan_forbidden = body_code in ("401", "403")
                if plan_forbidden and getattr(spec, "optional_if_plan_forbidden", False):
                    # A single not-in-plan endpoint must go gray alone — feeding
                    # 403 into the provider-wide backoff starves every endpoint
                    # scheduled after it for the whole backoff window.
                    self.limiter.observe_response(200, headers)
                else:
                    self.limiter.observe_response(403 if plan_forbidden else 500, headers)
                return CoinGlassResponse(
                    spec.endpoint_id, symbol, response.status_code, payload,
                    headers=headers,
                    error_class=f"IN_BODY_{body_code}_" + str(
                        (payload or {}).get("msg") or ""
                    ).upper().replace(" ", "_")[:40],
                )
            self.limiter.observe_response(response.status_code, headers)
            return CoinGlassResponse(spec.endpoint_id, symbol, response.status_code, payload, headers=headers)
        except Exception as exc:  # noqa: BLE001
            self.limiter.observe_response(None, {})
            return CoinGlassResponse(spec.endpoint_id, symbol, None, None, error_class=type(exc).__name__)


def _coin(symbol: str) -> str:
    value = str(symbol).upper()
    return value[:-4] if value.endswith("USDT") else value


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        return None
