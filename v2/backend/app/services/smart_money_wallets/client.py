"""Read-only Moralis HTTP client guarded by CU budget."""

from __future__ import annotations

import hashlib
import os
from contextlib import suppress
from typing import Any

import httpx
from app.services.smart_money_wallets.endpoint_registry import (
    MORALIS_DEEP_INDEX_BASE_URL,
    MoralisEndpointSpec,
)
from app.services.smart_money_wallets.models import MoralisResponse
from app.services.smart_money_wallets.rate_limit import (
    MORALIS_TIMEOUT_SECONDS,
    MoralisRateLimiter,
)

DEFAULT_BASE_URL = MORALIS_DEEP_INDEX_BASE_URL


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
        # A real client without a durable ledger must fail closed.  Tests that
        # exercise the local-only limiter can still opt into it explicitly.
        self.limiter = limiter or MoralisRateLimiter(require_persistent_ledger=True)
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
            return MoralisResponse(
                spec.endpoint_id,
                chain,
                wallet,
                token,
                symbol,
                None,
                None,
                error_class="STREAM_ENDPOINT_NOT_POLLED",
            )
        contract_error = _request_contract_error(
            spec,
            actual_base_url=self.base_url,
        )
        if contract_error is not None:
            return MoralisResponse(
                spec.endpoint_id,
                chain,
                wallet,
                token,
                symbol,
                None,
                None,
                error_class=contract_error,
            )
        if not str(chain).strip():
            return MoralisResponse(
                spec.endpoint_id,
                chain,
                wallet,
                token,
                symbol,
                None,
                None,
                error_class="CHAIN_REQUIRED",
            )
        if spec.requires_wallet and not str(wallet or "").strip():
            return MoralisResponse(
                spec.endpoint_id,
                chain,
                wallet,
                token,
                symbol,
                None,
                None,
                error_class="WALLET_REQUIRED",
            )
        if spec.requires_token and not str(token or "").strip():
            return MoralisResponse(
                spec.endpoint_id,
                chain,
                wallet,
                token,
                symbol,
                None,
                None,
                error_class="TOKEN_REQUIRED",
            )
        if not self.api_key_present:
            return MoralisResponse(
                spec.endpoint_id,
                chain,
                wallet,
                token,
                symbol,
                401,
                None,
                error_class="API_KEY_MISSING",
            )
        try:
            path = spec.path_template.format(chain=chain, wallet=wallet or "", token=token or "")
        except Exception as exc:  # No request was attempted and no CU was reserved.
            return MoralisResponse(
                spec.endpoint_id,
                chain,
                wallet,
                token,
                symbol,
                None,
                None,
                error_class=type(exc).__name__,
            )
        decision = self.limiter.allow_request(estimated_cu=spec.cu_cost)
        if not decision.allowed:
            return MoralisResponse(
                spec.endpoint_id,
                chain,
                wallet,
                token,
                symbol,
                None,
                None,
                error_class=decision.reason,
            )
        try:
            close_client = self.http_client is None
            client = self.http_client or httpx.Client(timeout=MORALIS_TIMEOUT_SECONDS)
            try:
                response = client.get(
                    f"{self.base_url}{path}",
                    headers={"X-API-Key": str(self.api_key), "accept": "application/json"},
                )
            finally:
                if close_client:
                    with suppress(Exception):
                        client.close()
            payload = _safe_json(response)
            headers = dict(response.headers)
            self.limiter.observe_response(response.status_code)
            reconciliation = self.limiter.reconcile_response(
                reservation=decision.reservation,
                headers=headers,
                estimated_cu=spec.cu_cost,
                http_status=response.status_code,
            )
            if not reconciliation.applied:
                # The provider is optional.  Never publish a response whose CU
                # accounting could not be durably reconciled.
                return MoralisResponse(
                    spec.endpoint_id,
                    chain,
                    wallet,
                    token,
                    symbol,
                    response.status_code,
                    None,
                    headers=headers,
                    error_class=reconciliation.reason,
                )
            return MoralisResponse(
                spec.endpoint_id,
                chain,
                wallet,
                token,
                symbol,
                response.status_code,
                payload,
                headers=headers,
            )
        except Exception as exc:  # noqa: BLE001
            self.limiter.observe_response(None)
            # Delivery is ambiguous after dispatch.  Retain the pre-call
            # reservation conservatively; a process crash does the same.
            self.limiter.retain_ambiguous_reservation(decision.reservation)
            return MoralisResponse(
                spec.endpoint_id,
                chain,
                wallet,
                token,
                symbol,
                None,
                None,
                error_class=type(exc).__name__,
            )


def _request_contract_error(
    spec: MoralisEndpointSpec,
    *,
    actual_base_url: str | None = None,
) -> str | None:
    if not spec.polling_supported:
        return spec.polling_block_reason or "ENDPOINT_REQUEST_CONTRACT_UNSUPPORTED"
    if spec.http_method != "GET":
        return "ENDPOINT_HTTP_METHOD_UNSUPPORTED"
    if spec.documented_base_url != MORALIS_DEEP_INDEX_BASE_URL:
        return "ENDPOINT_BASE_URL_UNSUPPORTED"
    if actual_base_url is not None and actual_base_url.rstrip("/") != spec.documented_base_url:
        return "ENDPOINT_CLIENT_BASE_URL_MISMATCH"
    if spec.request_body_shape is not None:
        return "ENDPOINT_REQUEST_BODY_UNSUPPORTED"
    query = spec.path_template.partition("?")[2]
    actual_query_shape = tuple(component for component in query.split("&") if component)
    if actual_query_shape != spec.query_parameter_shape:
        return "ENDPOINT_QUERY_CONTRACT_MISMATCH"
    return None


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        return None
