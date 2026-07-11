"""Binance USD-M futures adapter for WebSocket-primary signed reads.

Binance account/trader reads are WebSocket API primary. REST signed reads are
fallback-only because repeated REST account polling can trigger IP bans. Write
style endpoints stay blocked unless their explicit operator probe flag is set
by environment. Secrets are never returned in request metadata.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlencode

import httpx

from v2.backend.app.services.binance_unified_websocket_transport import (
    binance_rest_fallback_decision,
    binance_rest_fallback_allowed as unified_binance_rest_fallback_allowed,
    binance_ws_api_url,
    build_signed_ws_api_request,
    default_ws_api_sender,
    redact_ws_api_payload,
    resolve_binance_credential_binding,
    transport_policy_snapshot,
)
from v2.backend.app.services.execution.order_intent_contract import (
    operator_leverage_mutation_allowed,
    operator_margin_mutation_allowed,
    operator_test_order_allowed,
)

SCHEMA_VERSION = "binance_usdm_adapter_v1"
DEFAULT_BASE_URL = "https://fapi.binance.com"
TESTNET_BASE_URL = "https://testnet.binancefuture.com"

REST_FALLBACK_ENV = "BINANCE_REST_FALLBACK_ALLOWED"

SIGNED_WS_READ_METHODS = (
    "account.status",
    "v2/account.status",
    "account.balance",
    "v2/account.balance",
    "account.position",
    "v2/account.position",
    "openOrders.status",
)

SIGNED_READ_ENDPOINTS = (
    "/fapi/v3/account",
    "/fapi/v3/balance",
    "/fapi/v1/positionSide/dual",
    "/fapi/v1/accountConfig",
    "/fapi/v1/symbolConfig",
    "/fapi/v1/leverageBracket",
    "/fapi/v1/commissionRate",
    "/fapi/v1/rateLimit/order",
    "/fapi/v1/openOrders",
    "/fapi/v3/positionRisk",
)

PUBLIC_ENDPOINTS = (
    "/fapi/v1/exchangeInfo",
    "/fapi/v1/time",
    "/fapi/v1/premiumIndex",
    "/fapi/v1/depth",
    "/fapi/v1/ticker/price",
    "/fapi/v1/ticker/bookTicker",
    "/fapi/v1/symbolAdlRisk",
)

MUTATION_ENDPOINTS = (
    "/fapi/v1/order",
    "/fapi/v1/leverage",
    "/fapi/v1/marginType",
)


def _redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {key: ("<redacted>" if key.lower() in {"x-mbx-apikey", "authorization"} else value) for key, value in headers.items()}


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class BinanceUSDMAdapter:
    api_key: str | None = None
    api_secret: str | None = None
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> "BinanceUSDMAdapter":
        binding = resolve_binance_credential_binding()
        testnet = os.environ.get("BINANCE_TESTNET", "").lower() == "true"
        return cls(
            api_key=binding.api_key or os.environ.get("BINANCE_FUT_API_KEY") or os.environ.get("BINANCE_API_KEY"),
            api_secret=(
                binding.api_secret
                or os.environ.get("BINANCE_FUT_API_SECRET")
                or os.environ.get("BINANCE_API_SECRET")
                or os.environ.get("BINANCE_SECRET_KEY")
            ),
            base_url=os.environ.get("BINANCE_USDM_REST_BASE_URL", TESTNET_BASE_URL if testnet else DEFAULT_BASE_URL),
        )

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _headers(self) -> dict[str, str]:
        return {"X-MBX-APIKEY": self.api_key or ""}

    def rest_fallback_allowed(self) -> bool:
        return unified_binance_rest_fallback_allowed()

    def signed_ws_contract(self, method: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        allowed = method in SIGNED_WS_READ_METHODS
        if self.has_credentials:
            payload = build_signed_ws_api_request(
                method=method,
                params=dict(params or {}),
                api_key=self.api_key or "",
                api_secret=self.api_secret or "",
            )
            redacted_payload = redact_ws_api_payload(payload)
        else:
            redacted_payload = {
                "id": None,
                "method": method,
                "params": {"apiKey": "[missing-credentials]", "signature": "[missing-credentials]"},
            }
        return {
            "schema_version": SCHEMA_VERSION,
            "transport": "websocket_api_primary",
            "endpoint": binance_ws_api_url(),
            "method": method,
            "signed_ws_read_method": allowed,
            "has_credentials": self.has_credentials,
            "payload_redacted": redacted_payload,
            "would_call": bool(allowed and self.has_credentials),
            "api_secret_exposed": False,
            "api_key_exposed": False,
            "places_real_order": False,
        }

    def signed_ws_read(self, method: str, params: Mapping[str, Any] | None = None, *, execute: bool = False) -> dict[str, Any]:
        contract = self.signed_ws_contract(method, params)
        if method not in SIGNED_WS_READ_METHODS:
            return {**contract, "status": "BLOCKED_UNSUPPORTED_SIGNED_WS_READ_METHOD"}
        if not self.has_credentials:
            return {**contract, "status": "SIGNED_WS_READ_BLOCKED_MISSING_ENV"}
        if not execute:
            return {**contract, "status": "SIGNED_WS_READ_READY_NOT_EXECUTED"}
        payload = build_signed_ws_api_request(
            method=method,
            params=dict(params or {}),
            api_key=self.api_key or "",
            api_secret=self.api_secret or "",
        )
        result = default_ws_api_sender(endpoint=binance_ws_api_url(), payload=payload)
        response = result.get("response") or {}
        return {
            **contract,
            "status": "SIGNED_WS_READ_EXECUTED" if result.get("ok") else "SIGNED_WS_READ_ERROR",
            "ws_status_code": result.get("status_code"),
            "error_type": result.get("error_type"),
            "response_json": response,
            "response_redacted": redact_ws_api_payload(response if isinstance(response, Mapping) else {}),
        }

    def sign_params(self, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not self.api_secret:
            raise ValueError("BINANCE_API_SECRET_MISSING")
        payload = {k: v for k, v in dict(params or {}).items() if v is not None}
        payload.setdefault("timestamp", _now_ms())
        query = urlencode(payload, doseq=True)
        signature = hmac.new(self.api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
        return {**payload, "signature": signature}

    def signed_get_contract(self, path: str, params: Mapping[str, Any] | None = None, *, fallback_reason: str | None = None) -> dict[str, Any]:
        allowed = path in SIGNED_READ_ENDPOINTS
        signed = self.sign_params(params) if self.has_credentials else {**dict(params or {}), "timestamp": _now_ms(), "signature": "<missing-credentials>"}
        redacted_params = {**signed, "signature": "<redacted>"}
        fallback = binance_rest_fallback_decision(
            endpoint=f"GET {path}",
            fallback_reason=fallback_reason,
            role="signed_read_recovery",
        )
        rest_fallback_allowed = bool(fallback["request_allowed"])
        return {
            "schema_version": SCHEMA_VERSION,
            "transport": "rest_fallback_only",
            "method": "GET",
            "path": path,
            "url": f"{self.base_url}{path}",
            "signed_read_endpoint": allowed,
            "has_credentials": self.has_credentials,
            "headers": _redact_headers(self._headers()),
            "params_redacted": redacted_params,
            "rest_fallback_allowed": rest_fallback_allowed,
            "rest_fallback_reason": fallback_reason,
            "rest_fallback_blocked_reason": fallback["rest_fallback_blocked_reason"],
            "rest_used_as_primary": False,
            "would_call": bool(allowed and self.has_credentials and rest_fallback_allowed),
            "api_secret_exposed": False,
            "api_key_exposed": False,
            "places_real_order": False,
        }

    def signed_get(self, path: str, params: Mapping[str, Any] | None = None, *, execute: bool = False, fallback_reason: str | None = None) -> dict[str, Any]:
        contract = self.signed_get_contract(path, params, fallback_reason=fallback_reason)
        if path not in SIGNED_READ_ENDPOINTS:
            return {**contract, "status": "BLOCKED_UNSUPPORTED_SIGNED_READ_ENDPOINT"}
        if not contract.get("rest_fallback_allowed"):
            return {**contract, "status": "REST_FALLBACK_BLOCKED_WEBSOCKET_PRIMARY"}
        if not self.has_credentials:
            return {**contract, "status": "SIGNED_READ_BLOCKED_MISSING_ENV"}
        if not execute:
            return {**contract, "status": "SIGNED_READ_READY_NOT_EXECUTED"}
        signed = self.sign_params(params)
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(f"{self.base_url}{path}", params=signed, headers=self._headers())
        status = "SIGNED_READ_EXECUTED" if 200 <= response.status_code < 300 else "SIGNED_READ_HTTP_ERROR"
        return {
            **contract,
            "status": status,
            "http_status_code": response.status_code,
            "response_json": response.json() if response.content else None,
        }

    def public_get_contract(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "transport": "public_rest_fallback_only",
            "method": "GET",
            "path": path,
            "url": f"{self.base_url}{path}",
            "public_endpoint": path in PUBLIC_ENDPOINTS,
            "params": dict(params or {}),
            "places_real_order": False,
            "api_secret_exposed": False,
            "api_key_exposed": False,
        }

    def blocked_mutation(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if path == "/fapi/v1/order":
            allowed = operator_test_order_allowed()
            flag = "BINANCE_TEST_ORDER_PROBE_ALLOWED"
        elif path == "/fapi/v1/leverage":
            allowed = operator_leverage_mutation_allowed()
            flag = "BINANCE_LEVERAGE_MUTATION_PROBE_ALLOWED"
        elif path == "/fapi/v1/marginType":
            allowed = operator_margin_mutation_allowed()
            flag = "BINANCE_MARGIN_MUTATION_PROBE_ALLOWED"
        else:
            allowed = False
            flag = "UNSUPPORTED_MUTATION_ENDPOINT"
        return {
            "schema_version": SCHEMA_VERSION,
            "method": "POST",
            "path": path,
            "mutation_endpoint": path in MUTATION_ENDPOINTS,
            "operator_flag": flag,
            "operator_flag_allows_probe": allowed,
            "would_submit_order": False,
            "would_submit_test_order": False,
            "places_real_order": False,
            "leverage_mutated": False,
            "margin_mutated": False,
            "params_redacted": dict(params or {}),
            "status": "BLOCKED_DRY_RUN_ONLY",
            "api_secret_exposed": False,
            "api_key_exposed": False,
        }


def endpoint_contract_matrix() -> dict[str, Any]:
    return {
        "schema_version": "binance_usdm_endpoint_contract_matrix_v1",
        "transport_policy": transport_policy_snapshot(),
        "account_and_trader_primary_transport": "binance_usdm_websocket_api",
        "public_market_primary_transport": "binance_usdm_public_websocket_stream_or_cache",
        "rest_role": "fallback_only_requires_BINANCE_REST_FALLBACK_ALLOWED_true_and_explicit_fallback_reason",
        "rest_used_as_primary": False,
        "signed_rest_fallback_supported_for_trader_readiness": False,
        "trader_account_reads_require_websocket_api": True,
        "trader_order_submit_requires_websocket_api": True,
        "signed_ws_read_methods": list(SIGNED_WS_READ_METHODS),
        "signed_ws_trade_methods": ["order.place"],
        "base_url": DEFAULT_BASE_URL,
        "testnet_base_url": TESTNET_BASE_URL,
        "signed_rest_fallback_endpoints": list(SIGNED_READ_ENDPOINTS),
        "public_rest_fallback_endpoints": list(PUBLIC_ENDPOINTS),
        "mutation_endpoints_blocked_by_default": list(MUTATION_ENDPOINTS),
        "uses_direct_hmac_httpx_adapter": True,
        "direct_hmac_httpx_adapter_role": "rest_fallback_only",
        "deprecated_futures_connector_required": False,
        "places_real_order": False,
    }
