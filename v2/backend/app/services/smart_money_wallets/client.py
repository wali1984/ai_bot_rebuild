"""Read-only Moralis HTTP client guarded by CU budget."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from app.services.smart_money_wallets.endpoint_registry import (
    MORALIS_DEEP_INDEX_BASE_URL,
    MORALIS_EVM_CHAIN_ALIASES,
    MoralisEndpointSpec,
)
from app.services.smart_money_wallets.models import (
    MAX_MORALIS_RAW_RESPONSE_BYTES,
    MORALIS_RAW_RESPONSE_BYTES_SCOPE,
    MoralisResponse,
)
from app.services.smart_money_wallets.rate_limit import (
    MORALIS_TIMEOUT_SECONDS,
    MoralisRateLimiter,
)

DEFAULT_BASE_URL = MORALIS_DEEP_INDEX_BASE_URL
_EVM_ADDRESS = re.compile(r"0x[0-9a-f]{40}", re.IGNORECASE)
_MORALIS_RESPONSE_READ_CHUNK_BYTES = 65_536


class BoundedStreamingRequiredError(RuntimeError):
    """Raised before dispatch when an injected client cannot stream safely."""


@dataclass(frozen=True)
class MoralisRequestIdentity:
    chain: str
    wallet: str | None
    token: str | None
    error_class: str | None = None


def prepare_request_identity(
    spec: MoralisEndpointSpec,
    *,
    chain: object,
    wallet: object | None = None,
    token: object | None = None,
) -> MoralisRequestIdentity:
    """Normalize and validate every value that can enter a request URL."""

    raw_chain = str(chain or "").strip().lower()
    if not raw_chain:
        return MoralisRequestIdentity("", None, None, "CHAIN_REQUIRED")
    normalized_chain = MORALIS_EVM_CHAIN_ALIASES.get(raw_chain)
    if normalized_chain is None:
        return MoralisRequestIdentity(raw_chain, None, None, "CHAIN_UNSUPPORTED")

    raw_wallet = None if wallet is None else str(wallet).strip().lower()
    raw_token = None if token is None else str(token).strip().lower()
    if spec.requires_wallet and not raw_wallet:
        return MoralisRequestIdentity(normalized_chain, None, raw_token, "WALLET_REQUIRED")
    if spec.requires_token and not raw_token:
        return MoralisRequestIdentity(normalized_chain, raw_wallet, None, "TOKEN_REQUIRED")
    if raw_wallet is not None and _EVM_ADDRESS.fullmatch(raw_wallet) is None:
        return MoralisRequestIdentity(
            normalized_chain,
            raw_wallet,
            raw_token,
            "WALLET_ADDRESS_INVALID",
        )
    if raw_token is not None and _EVM_ADDRESS.fullmatch(raw_token) is None:
        return MoralisRequestIdentity(
            normalized_chain,
            raw_wallet,
            raw_token,
            "TOKEN_ADDRESS_INVALID",
        )
    return MoralisRequestIdentity(normalized_chain, raw_wallet, raw_token)


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
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("MORALIS_API_KEY")
        self.base_url = (base_url or os.getenv("MORALIS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        # A real client without a durable ledger must fail closed.  Tests that
        # exercise the local-only limiter can still opt into it explicitly.
        self.limiter = limiter or MoralisRateLimiter(require_persistent_ledger=True)
        self.http_client = http_client
        self.now_factory = now_factory or (lambda: datetime.now(UTC))

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
        identity = prepare_request_identity(
            spec,
            chain=chain,
            wallet=wallet,
            token=token,
        )
        if identity.error_class is not None:
            return MoralisResponse(
                spec.endpoint_id,
                identity.chain,
                identity.wallet,
                identity.token,
                symbol,
                None,
                None,
                error_class=identity.error_class,
            )
        chain = identity.chain
        wallet = identity.wallet
        token = identity.token
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
            path = _encoded_request_path(
                spec,
                chain=chain,
                wallet=wallet,
                token=token,
            )
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
        request_dispatched = False
        transport_started_at: str | None = None
        try:
            close_client = self.http_client is None
            client = self.http_client or httpx.Client(timeout=MORALIS_TIMEOUT_SECONDS)
            try:
                stream_request = getattr(client, "stream", None)
                if not callable(stream_request):
                    raise BoundedStreamingRequiredError
                transport_started_at = _clock_text(self.now_factory)
                request_dispatched = True
                request_url = f"{self.base_url}{path}"
                request_headers = {
                    "X-API-Key": str(self.api_key),
                    "accept": "application/json",
                    # Decoded streaming can allocate far beyond the retained
                    # evidence cap (for example, a gzip expansion bomb).  The
                    # response contract below rejects any non-identity coding
                    # before body iteration and hashes the exact identity body.
                    "accept-encoding": "identity",
                }
                with stream_request(
                    "GET",
                    request_url,
                    headers=request_headers,
                ) as response:
                    (
                        raw_response_bytes,
                        raw_response_byte_count,
                        raw_response_sha256,
                        response_error,
                    ) = _read_bounded_response_bytes(response)
                    response_status_code = response.status_code
                    headers: dict[str, object] = dict(response.headers)
                observed_at = _clock_text(self.now_factory)
            finally:
                if close_client:
                    with suppress(Exception):
                        client.close()
            ingested_at = _clock_text(self.now_factory) if raw_response_bytes is not None else None
            payload: Any = None
            if raw_response_bytes is not None:
                payload, response_error = _safe_json(raw_response_bytes)
            self.limiter.observe_response(response_status_code)
            reconciliation = self.limiter.reconcile_response(
                reservation=decision.reservation,
                headers=headers,
                estimated_cu=spec.cu_cost,
                http_status=response_status_code,
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
                    response_status_code,
                    None,
                    headers=headers,
                    error_class=reconciliation.reason,
                    request_dispatched=True,
                    raw_response_bytes=raw_response_bytes,
                    raw_response_sha256=raw_response_sha256,
                    raw_response_byte_count=raw_response_byte_count,
                    raw_response_bytes_scope=MORALIS_RAW_RESPONSE_BYTES_SCOPE,
                    transport_started_at=transport_started_at,
                    observed_at=observed_at,
                    ingested_at=ingested_at,
                )
            return MoralisResponse(
                spec.endpoint_id,
                chain,
                wallet,
                token,
                symbol,
                response_status_code,
                payload if response_error is None else None,
                headers=headers,
                error_class=response_error,
                request_dispatched=True,
                raw_response_bytes=raw_response_bytes,
                raw_response_sha256=raw_response_sha256,
                raw_response_byte_count=raw_response_byte_count,
                raw_response_bytes_scope=MORALIS_RAW_RESPONSE_BYTES_SCOPE,
                transport_started_at=transport_started_at,
                observed_at=observed_at,
                ingested_at=ingested_at,
            )
        except Exception as exc:  # noqa: BLE001
            self.limiter.observe_response(None)
            if request_dispatched:
                # Delivery is ambiguous after dispatch. Retain the pre-call
                # reservation conservatively; a process crash does the same.
                self.limiter.retain_ambiguous_reservation(decision.reservation)
            else:
                # Client construction failed before transport dispatch.
                self.limiter.refund_pending(request_was_not_sent=True)
            return MoralisResponse(
                spec.endpoint_id,
                chain,
                wallet,
                token,
                symbol,
                None,
                None,
                error_class=type(exc).__name__,
                request_dispatched=request_dispatched,
                transport_started_at=transport_started_at,
            )


def _request_contract_error(
    spec: MoralisEndpointSpec,
    *,
    actual_base_url: str | None = None,
) -> str | None:
    if spec.transport_alias_of is not None:
        return "ENDPOINT_TRANSPORT_ALIAS_NOT_DIRECTLY_POLLED"
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
    for component in spec.query_parameter_shape:
        key, separator, _value = component.partition("=")
        if not separator or re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", key) is None:
            return "ENDPOINT_QUERY_CONTRACT_MISMATCH"
    return None


def _encoded_request_path(
    spec: MoralisEndpointSpec,
    *,
    chain: str,
    wallet: str | None,
    token: str | None,
) -> str:
    values = {
        "chain": chain,
        "wallet": wallet or "",
        "token": token or "",
    }
    path_template = spec.path_template.partition("?")[0]
    encoded_values = {name: quote(value, safe="") for name, value in values.items()}
    path = path_template.format(**encoded_values)
    query_pairs: list[tuple[str, str]] = []
    for component in spec.query_parameter_shape:
        key, separator, value_template = component.partition("=")
        if not separator:
            raise ValueError("query component is missing '='")
        query_pairs.append((key, value_template.format(**values)))
    return str(f"{path}?{urlencode(query_pairs)}" if query_pairs else path)


def _safe_json(raw_response_bytes: bytes) -> tuple[Any, str | None]:
    try:
        return (
            json.loads(
                raw_response_bytes,
                object_pairs_hook=_reject_duplicate_object_keys,
                parse_constant=_reject_nonfinite_json_constant,
            ),
            None,
        )
    except (RecursionError, TypeError, UnicodeError, ValueError):
        return None, "RAW_RESPONSE_JSON_INVALID"


def _read_bounded_response_bytes(
    response: httpx.Response,
) -> tuple[bytes | None, int | None, str | None, str | None]:
    content_encoding = str(response.headers.get("content-encoding") or "").strip().lower()
    if content_encoding not in {"", "identity"}:
        return None, None, None, "RAW_RESPONSE_CONTENT_ENCODING_UNSUPPORTED"

    declared_byte_count: int | None = None
    raw_content_length = response.headers.get("content-length")
    if raw_content_length is not None:
        content_length = str(raw_content_length).strip()
        try:
            declared_byte_count = int(content_length)
        except ValueError:
            return None, None, None, "RAW_RESPONSE_CONTENT_LENGTH_INVALID"
        if declared_byte_count < 0:
            return None, None, None, "RAW_RESPONSE_CONTENT_LENGTH_INVALID"
        if declared_byte_count > MAX_MORALIS_RAW_RESPONSE_BYTES:
            return None, None, None, "RAW_RESPONSE_BYTE_LIMIT_EXCEEDED"

    chunks: list[bytes] = []
    byte_count = 0
    digest = hashlib.sha256()
    for chunk in response.iter_raw(chunk_size=_MORALIS_RESPONSE_READ_CHUNK_BYTES):
        next_count = byte_count + len(chunk)
        if next_count > MAX_MORALIS_RAW_RESPONSE_BYTES:
            return None, None, None, "RAW_RESPONSE_BYTE_LIMIT_EXCEEDED"
        chunks.append(chunk)
        digest.update(chunk)
        byte_count = next_count
    if declared_byte_count is not None and declared_byte_count != byte_count:
        return None, None, None, "RAW_RESPONSE_CONTENT_LENGTH_MISMATCH"
    return b"".join(chunks), byte_count, digest.hexdigest(), None


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_nonfinite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _clock_text(now_factory: Callable[[], datetime]) -> str:
    value = now_factory()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Moralis transport clock must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
