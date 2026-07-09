"""Read-only Moralis HTTP client guarded by CU budget."""

from __future__ import annotations

import hashlib
import os
from typing import Any

import httpx

from app.services.smart_money_wallets.endpoint_registry import MoralisEndpointSpec
from app.services.smart_money_wallets.models import MoralisResponse
from app.services.smart_money_wallets.rate_limit import (
    MORALIS_TIMEOUT_SECONDS,
    MoralisRateLimiter,
)


DEFAULT_BASE_URL = "https://deep-index.moralis.io/api/v2.2"


def key_hash_prefix(api_key: str | None) -> str | None:
    if not api_key:
        return None
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:8]


class MoralisClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        limiter: MoralisRateLimiter | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("MORALIS_API_KEY")
        self.base_url = (base_url or os.getenv("MORALIS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.limiter = limiter or MoralisRateLimiter()
        self.http_client = http_client

    @property
    def api_key_present(self) -> bool:
        return bool(str(self.api_key or "").strip())

    def get(
        self,
        spec: MoralisEndpointSpec,
        *,
        chain: str = "eth",
        wallet: str | None = None,
        token: str | None = None,
        symbol: str | None = None,
    ) -> MoralisResponse:
        if spec.stream_based:
            return MoralisResponse(spec.endpoint_id, chain, wallet, token, symbol, None, None, error_class="STREAM_ENDPOINT_NOT_POLLED")
        if not self.api_key_present:
            return MoralisResponse(spec.endpoint_id, chain, wallet, token, symbol, 401, None, error_class="API_KEY_MISSING")
        decision = self.limiter.allow_request(estimated_cu=spec.cu_cost)
        if not decision.allowed:
            return MoralisResponse(spec.endpoint_id, chain, wallet, token, symbol, None, None, error_class=decision.reason)
        try:
            path = spec.path_template.format(chain=chain, wallet=wallet or "", token=token or "")
            close_client = self.http_client is None
            client = self.http_client or httpx.Client(timeout=MORALIS_TIMEOUT_SECONDS)
            try:
                response = client.get(
                    f"{self.base_url}{path}",
                    headers={"X-API-Key": str(self.api_key), "accept": "application/json"},
                )
            finally:
                if close_client:
                    client.close()
            payload = _safe_json(response)
            headers = dict(response.headers)
            self.limiter.observe_response(response.status_code)
            if 200 <= response.status_code <= 299:
                self.limiter.charge(estimated_cu=spec.cu_cost, headers=headers)
            return MoralisResponse(spec.endpoint_id, chain, wallet, token, symbol, response.status_code, payload, headers=headers)
        except Exception as exc:  # noqa: BLE001
            self.limiter.observe_response(None)
            return MoralisResponse(spec.endpoint_id, chain, wallet, token, symbol, None, None, error_class=type(exc).__name__)


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        return None
