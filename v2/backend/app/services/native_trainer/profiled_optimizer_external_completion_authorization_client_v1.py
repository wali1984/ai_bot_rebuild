"""Pinned HTTPS transport for completion-authorization requests.

This client sends only a caller-supplied, already durable, exact prepared
request to a purpose-specific compare-and-authorize endpoint.  It owns no
private signing key, journal, optimizer, checkpoint, model, prediction, paper,
live, order, or execution authority.  Ambiguous delivery is recovered only by
replaying the byte-identical request and idempotency key.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Any, Final, NoReturn, Protocol, cast, runtime_checkable
from urllib.parse import quote, unquote_to_bytes, urlsplit, urlunsplit

import httpx

from .profiled_optimizer_external_completion_request_v1 import (
    MAX_PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BYTES,
    MAX_PROFILED_OPTIMIZER_COMPLETION_REQUEST_BYTES,
    ProfiledOptimizerExternalCompletionPreparedRequestV1,
    ProfiledOptimizerExternalCompletionRequestV1Error,
    VerifiedProfiledOptimizerExternalCompletionResponseV1,
    rehydrate_profiled_optimizer_external_completion_prepared_request_v1,
    verify_profiled_optimizer_external_completion_response_v1,
)

PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_CLIENT_V1_SCHEMA_VERSION: Final = (
    "profiled_optimizer_completion_authorization_client_v1"
)
PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_ROUTE_SUFFIX: Final = (
    "completion-authorizations:compare-and-authorize"
)

# Transport/resource limits only; these do not select markets, samples, risk,
# leverage, margin, or optimizer behavior.
ED25519_PUBLIC_KEY_BYTES: Final = 32
MAX_COMPLETION_AUTHORIZATION_WIRE_BYTES: Final = max(
    MAX_PROFILED_OPTIMIZER_COMPLETION_REQUEST_BYTES,
    MAX_PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BYTES,
)
MIN_COMPLETION_AUTHORIZATION_TIMEOUT_SECONDS: Final = 0.1
MAX_COMPLETION_AUTHORIZATION_TIMEOUT_SECONDS: Final = 60.0

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$", re.ASCII)
_BEARER_TOKEN_RE = re.compile(r"^[\x21-\x7e]{16,4096}$", re.ASCII)
_VISIBLE_ASCII_URL_RE = re.compile(r"^[\x21-\x7e]+$", re.ASCII)
_SAFE_BASE_PATH_RE = re.compile(r"^(?:/[A-Za-z0-9._~-]+)*$", re.ASCII)
_PURPOSE_ROUTE_RE = re.compile(
    r"^/namespaces/(?P<namespace>(?:[A-Za-z0-9._~-]|%[0-9A-F]{2})+)/"
    r"completion-authorizations:compare-and-authorize$",
    re.ASCII,
)


class ProfiledOptimizerCompletionAuthorizationClientV1Error(RuntimeError):
    """The completion-authorization transport failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise ProfiledOptimizerCompletionAuthorizationClientV1Error(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _identifier(value: object, *, reason: str) -> str:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        _fail(reason)
    return value


def _canonical_purpose_route(path: str) -> bool:
    match = _PURPOSE_ROUTE_RE.fullmatch(path)
    if match is None:
        return False
    encoded_namespace = match.group("namespace")
    try:
        namespace = unquote_to_bytes(encoded_namespace).decode("ascii", errors="strict")
    except (UnicodeDecodeError, ValueError):
        return False
    return (
        _IDENTIFIER_RE.fullmatch(namespace) is not None
        and quote(namespace, safe="") == encoded_namespace
    )


@dataclass(frozen=True, slots=True)
class ProfiledOptimizerCompletionAuthorizationWireResponseV1:
    status_code: int
    content_type: str
    body: bytes

    def __post_init__(self) -> None:
        if (
            type(self.status_code) is not int
            or not 100 <= self.status_code <= 599
            or type(self.content_type) is not str
            or type(self.body) is not bytes
            or len(self.body) > MAX_COMPLETION_AUTHORIZATION_WIRE_BYTES
        ):
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_WIRE_RESPONSE_INVALID")


@runtime_checkable
class ProfiledOptimizerCompletionAuthorizationWireTransportV1(Protocol):
    def request(
        self,
        *,
        method: str,
        path: str,
        body: bytes,
        idempotency_key: str,
    ) -> ProfiledOptimizerCompletionAuthorizationWireResponseV1: ...


class ProfiledOptimizerCompletionAuthorizationHttpsTransportV1:
    """No-redirect HTTPS transport with bounded identity-encoded responses."""

    __slots__ = ("_authorization_header", "_base_url", "_client")

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str,
        timeout_seconds: float,
        _test_http_transport: httpx.MockTransport | None = None,
    ) -> None:
        if (
            type(base_url) is not str
            or not base_url
            or _VISIBLE_ASCII_URL_RE.fullmatch(base_url) is None
        ):
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BASE_URL_INVALID")
        try:
            parsed = urlsplit(base_url)
            parsed_port = parsed.port
        except ValueError:
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BASE_URL_INVALID")
        path_without_documented_trailing_slash = (
            parsed.path[:-1] if parsed.path.endswith("/") else parsed.path
        )
        path_segments = (
            path_without_documented_trailing_slash.split("/")[1:]
            if path_without_documented_trailing_slash
            else []
        )
        normalized_base_url = urlunsplit(
            (
                "https",
                parsed.netloc,
                path_without_documented_trailing_slash,
                "",
                "",
            )
        )
        supplied_without_documented_trailing_slash = (
            base_url[:-1] if base_url.endswith("/") else base_url
        )
        try:
            httpx_normalized_base_url = str(httpx.URL(normalized_base_url))
        except (TypeError, ValueError):
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BASE_URL_INVALID")
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.isascii()
            or not parsed.netloc.isascii()
            or "\\" in parsed.netloc
            or "%" in parsed.netloc
            or parsed.netloc.endswith(":")
            or parsed_port == 0
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or _SAFE_BASE_PATH_RE.fullmatch(
                path_without_documented_trailing_slash
            )
            is None
            or any(segment in {"", ".", ".."} for segment in path_segments)
            or normalized_base_url
            != supplied_without_documented_trailing_slash
            or httpx_normalized_base_url != normalized_base_url
        ):
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BASE_URL_INVALID")
        self._base_url = normalized_base_url
        if (
            type(bearer_token) is not str
            or _BEARER_TOKEN_RE.fullmatch(bearer_token) is None
        ):
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BEARER_INVALID")
        if (
            type(timeout_seconds) not in {int, float}
            or not MIN_COMPLETION_AUTHORIZATION_TIMEOUT_SECONDS
            <= float(timeout_seconds)
            <= MAX_COMPLETION_AUTHORIZATION_TIMEOUT_SECONDS
        ):
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_TIMEOUT_INVALID")
        if _test_http_transport is not None and type(_test_http_transport) is not (
            httpx.MockTransport
        ):
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_TEST_TRANSPORT_INVALID")
        self._authorization_header = f"Bearer {bearer_token}"
        self._client = httpx.Client(
            follow_redirects=False,
            timeout=float(timeout_seconds),
            trust_env=False,
            verify=True,
            transport=_test_http_transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ProfiledOptimizerCompletionAuthorizationHttpsTransportV1:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def request(
        self,
        *,
        method: str,
        path: str,
        body: bytes,
        idempotency_key: str,
    ) -> ProfiledOptimizerCompletionAuthorizationWireResponseV1:
        if method != "POST":
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_HTTP_METHOD_INVALID")
        if (
            type(path) is not str
            or not path.startswith("/")
            or "//" in path
            or ".." in path.split("/")
            or "?" in path
            or "#" in path
            or not path.isascii()
            or not _canonical_purpose_route(path)
        ):
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_HTTP_PATH_INVALID")
        if (
            type(body) is not bytes
            or not body
            or len(body) > MAX_COMPLETION_AUTHORIZATION_WIRE_BYTES
        ):
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_HTTP_BODY_INVALID")
        if not _valid_sha256(idempotency_key):
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_IDEMPOTENCY_INVALID")
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Authorization": self._authorization_header,
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
            "User-Agent": "ai-bot-v2-profiled-completion-authorization-client/1",
        }
        try:
            with self._client.stream(
                "POST",
                f"{self._base_url}{path}",
                headers=headers,
                content=body,
                follow_redirects=False,
            ) as response:
                content_encoding = str(response.headers.get("content-encoding", ""))
                if content_encoding.strip().lower() not in {"", "identity"}:
                    _fail(
                        "PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_CONTENT_ENCODING_INVALID"
                    )
                payload = bytearray()
                for chunk in response.iter_raw():
                    if len(payload) + len(chunk) > MAX_COMPLETION_AUTHORIZATION_WIRE_BYTES:
                        _fail(
                            "PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_RESPONSE_TOO_LARGE"
                        )
                    payload.extend(chunk)
                result = ProfiledOptimizerCompletionAuthorizationWireResponseV1(
                    status_code=int(response.status_code),
                    content_type=str(response.headers.get("content-type", "")),
                    body=bytes(payload),
                )
        except ProfiledOptimizerCompletionAuthorizationClientV1Error:
            raise
        except httpx.HTTPError as exc:
            raise ProfiledOptimizerCompletionAuthorizationClientV1Error(
                "PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_HTTP_TRANSPORT_FAILED:"
                f"{type(exc).__name__}"
            ) from exc
        if result.body and result.content_type.split(";", 1)[0].strip().lower() != (
            "application/json"
        ):
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_CONTENT_TYPE_INVALID")
        return result


class PinnedProfiledOptimizerCompletionAuthorizationClientV1:
    """Pinned-key completion authorization dispatcher and verifier."""

    __slots__ = (
        "_close_transport_on_close",
        "_closed",
        "_public_key_bytes",
        "_public_key_sha256",
        "_transport",
        "_witness_id",
    )

    def __init__(
        self,
        *,
        transport: ProfiledOptimizerCompletionAuthorizationWireTransportV1,
        witness_id: str,
        witness_public_key_bytes: bytes,
        expected_witness_public_key_sha256: str,
        close_transport_on_close: bool = False,
    ) -> None:
        if not isinstance(
            transport,
            ProfiledOptimizerCompletionAuthorizationWireTransportV1,
        ):
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_TRANSPORT_INVALID")
        if type(close_transport_on_close) is not bool or (
            close_transport_on_close
            and not callable(getattr(transport, "close", None))
        ):
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_TRANSPORT_OWNERSHIP_INVALID")
        self._witness_id = _identifier(
            witness_id,
            reason="PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_WITNESS_ID_INVALID",
        )
        if (
            type(witness_public_key_bytes) is not bytes
            or len(witness_public_key_bytes) != ED25519_PUBLIC_KEY_BYTES
            or not _valid_sha256(expected_witness_public_key_sha256)
        ):
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_WITNESS_KEY_INVALID")
        key_bytes = bytes(witness_public_key_bytes)
        key_sha = hashlib.sha256(key_bytes).hexdigest()
        if not hmac.compare_digest(key_sha, expected_witness_public_key_sha256):
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_WITNESS_KEY_MISMATCH")
        self._transport = transport
        self._close_transport_on_close = close_transport_on_close
        self._closed = False
        self._public_key_bytes = key_bytes
        self._public_key_sha256 = key_sha

    @property
    def witness_id(self) -> str:
        return self._witness_id

    @property
    def witness_public_key_sha256(self) -> str:
        return self._public_key_sha256

    @property
    def witness_public_key_bytes(self) -> bytes:
        return bytes(self._public_key_bytes)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._close_transport_on_close:
            cast(Any, self._transport).close()

    def __enter__(self) -> PinnedProfiledOptimizerCompletionAuthorizationClientV1:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    @staticmethod
    def _path(namespace: str) -> str:
        return (
            f"/namespaces/{quote(namespace, safe='')}/"
            f"{PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_ROUTE_SUFFIX}"
        )

    def _reauthenticate_prepared(
        self,
        prepared: ProfiledOptimizerExternalCompletionPreparedRequestV1,
    ) -> None:
        if self._closed:
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_CLIENT_CLOSED")
        if type(prepared) is not ProfiledOptimizerExternalCompletionPreparedRequestV1:
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_PREPARED_TYPE_INVALID")
        prepared.__post_init__()
        if (
            prepared.witness_id != self._witness_id
            or prepared.witness_public_key_sha256 != self._public_key_sha256
        ):
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_PREPARED_WITNESS_MISMATCH")
        try:
            rehydrated = (
                rehydrate_profiled_optimizer_external_completion_prepared_request_v1(
                    request_bytes=prepared.request_bytes,
                )
            )
        except ProfiledOptimizerExternalCompletionRequestV1Error as exc:
            raise ProfiledOptimizerCompletionAuthorizationClientV1Error(
                "PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_PREPARED_REHYDRATE_FAILED"
            ) from exc
        if prepared != rehydrated or not hmac.compare_digest(
            prepared.request_bytes,
            rehydrated.request_bytes,
        ):
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_PREPARED_REAUTH_FAILED")

    def verify_authorization_envelope(
        self,
        *,
        prepared: ProfiledOptimizerExternalCompletionPreparedRequestV1,
        authorization_envelope_bytes: bytes,
    ) -> VerifiedProfiledOptimizerExternalCompletionResponseV1:
        """Verify exact response bytes without network or downstream authority."""

        self._reauthenticate_prepared(prepared)
        try:
            return verify_profiled_optimizer_external_completion_response_v1(
                prepared=prepared,
                authorization_envelope_bytes=authorization_envelope_bytes,
                witness_public_key_bytes=self._public_key_bytes,
            )
        except ProfiledOptimizerExternalCompletionRequestV1Error as exc:
            raise ProfiledOptimizerCompletionAuthorizationClientV1Error(
                "PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_RESPONSE_UNVERIFIED"
            ) from exc

    def dispatch_prepared_authorization(
        self,
        prepared: ProfiledOptimizerExternalCompletionPreparedRequestV1,
    ) -> VerifiedProfiledOptimizerExternalCompletionResponseV1:
        """POST exact durable bytes; retry ambiguity only with the same object."""

        self._reauthenticate_prepared(prepared)
        response = self._transport.request(
            method="POST",
            path=self._path(prepared.authorization_namespace),
            body=prepared.request_bytes,
            idempotency_key=prepared.idempotency_key,
        )
        if type(response) is not ProfiledOptimizerCompletionAuthorizationWireResponseV1:
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_RESPONSE_TYPE_INVALID")
        response.__post_init__()
        if response.status_code != 200:
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_HTTP_STATUS_INVALID")
        if response.content_type.split(";", 1)[0].strip().lower() != "application/json":
            _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_CONTENT_TYPE_INVALID")
        return self.verify_authorization_envelope(
            prepared=prepared,
            authorization_envelope_bytes=response.body,
        )


__all__ = (
    "MAX_COMPLETION_AUTHORIZATION_WIRE_BYTES",
    "PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_CLIENT_V1_SCHEMA_VERSION",
    "PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_ROUTE_SUFFIX",
    "PinnedProfiledOptimizerCompletionAuthorizationClientV1",
    "ProfiledOptimizerCompletionAuthorizationClientV1Error",
    "ProfiledOptimizerCompletionAuthorizationHttpsTransportV1",
    "ProfiledOptimizerCompletionAuthorizationWireResponseV1",
    "ProfiledOptimizerCompletionAuthorizationWireTransportV1",
)
