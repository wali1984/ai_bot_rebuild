"""Pinned HTTPS client for the independent profiled-training witness.

The local manifest/head/page factories deliberately cannot establish a
monotonic external history.  This module supplies the first concrete client
for that missing boundary.  It sends deterministic compare-and-append
requests to an HTTPS service, requires canonical bounded JSON, verifies every
event and receipt with one independently pinned Ed25519 public key, and reads
the appended event back before returning.

There is no private key, signing helper, optimizer, checkpoint writer, model
publisher, prediction path, or trading path here.  A successful return proves
only that the pinned witness signed the exact wire material and that the
service returned a coherent event through its read API.  Durable cross-restart
single-consumption state and the higher-level completion authorization remain
separate requirements.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, NoReturn, Protocol, cast, runtime_checkable
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_head_v1 import (
    MAX_PROFILED_OBSERVATION_HEAD_EVENT_BYTES,
    PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
    PROFILED_OBSERVATION_WITNESS_EVENT_V1_SCHEMA_VERSION,
    PROFILED_OBSERVATION_WITNESS_RECEIPT_V1_SCHEMA_VERSION,
    ProfiledTrainingObservationExternalWitnessAppendReceiptV1,
    ProfiledTrainingObservationExternalWitnessEventV1,
    ProfiledTrainingObservationExternalWitnessV1,
)

PROFILED_WITNESS_WIRE_EVENT_V1_SCHEMA_VERSION: Final = (
    "profiled_training_observation_external_witness_wire_event_v1"
)
PROFILED_WITNESS_WIRE_APPEND_RECEIPT_V1_SCHEMA_VERSION: Final = (
    "profiled_training_observation_external_witness_wire_append_receipt_v1"
)
PROFILED_WITNESS_COMPARE_APPEND_REQUEST_V1_SCHEMA_VERSION: Final = (
    "profiled_training_observation_external_witness_compare_append_request_v1"
)
PROFILED_WITNESS_WIRE_SIGNATURE_ALGORITHM: Final = "Ed25519"
PROFILED_WITNESS_WIRE_EVENT_SIGNATURE_DOMAIN: Final = (
    "v2/native-trainer/profiled-observation-external-witness-wire-event/v1"
)
PROFILED_WITNESS_WIRE_RECEIPT_SIGNATURE_DOMAIN: Final = (
    "v2/native-trainer/profiled-observation-external-witness-wire-receipt/v1"
)
PROFILED_WITNESS_COMPARE_APPEND_REQUEST_DOMAIN: Final = (
    "v2/native-trainer/profiled-observation-external-witness-compare-append-request/v1"
)

# Wire/parser/transport resource limits only.  These do not select markets,
# samples, labels, regimes, leverage, margin, risk, or optimizer parameters.
ED25519_PUBLIC_KEY_BYTES: Final = 32
ED25519_SIGNATURE_BYTES: Final = 64
MAX_PROFILED_WITNESS_WIRE_BYTES: Final = 6 * 1024 * 1024
MAX_PROFILED_WITNESS_RECEIPT_PAYLOAD_BYTES: Final = 256 * 1024
MAX_PROFILED_WITNESS_JSON_DEPTH: Final = 16
MAX_PROFILED_WITNESS_JSON_NODES: Final = 32_768
MAX_PROFILED_WITNESS_CONTAINER_ITEMS: Final = 8_192
MAX_PROFILED_WITNESS_TEXT_BYTES: Final = MAX_PROFILED_WITNESS_WIRE_BYTES
MAX_PROFILED_WITNESS_BOOTSTRAP_EVENTS: Final = 8_192
MIN_PROFILED_WITNESS_TIMEOUT_SECONDS: Final = 0.1
MAX_PROFILED_WITNESS_TIMEOUT_SECONDS: Final = 60.0

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SIGNATURE_RE = re.compile(r"^[0-9a-f]{128}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$", re.ASCII)
_BEARER_TOKEN_RE = re.compile(r"^[\x21-\x7e]{16,4096}$", re.ASCII)
_SAFE_BASE_PATH_RE = re.compile(r"^(?:/[A-Za-z0-9._~-]+)*$", re.ASCII)
_EVENT_FIELDS = {
    "schema_version",
    "signature_algorithm",
    "signature_domain",
    "witness_id",
    "namespace",
    "sequence",
    "previous_event_sha256",
    "event_sha256",
    "event_byte_count",
    "event_base64",
    "signed_at",
    "signature_hex",
}
_RECEIPT_FIELDS = {
    "schema_version",
    "signature_algorithm",
    "signature_domain",
    "witness_id",
    "namespace",
    "sequence",
    "previous_event_sha256",
    "event_sha256",
    "accepted_at",
    "request_sha256",
    "idempotency_key",
    "receipt_payload_sha256",
    "receipt_payload_byte_count",
    "receipt_payload_base64",
    "signature_hex",
}


class ProfiledTrainingExternalWitnessClientV1Error(RuntimeError):
    """The pinned witness transport or signed wire contract failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise ProfiledTrainingExternalWitnessClientV1Error(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _identifier(value: object, *, reason: str) -> str:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        _fail(reason)
    return value


def _positive_integer(value: object, *, reason: str, allow_zero: bool = False) -> int:
    if type(value) is not int or value < (0 if allow_zero else 1) or value > 2**63 - 1:
        _fail(reason)
    return value


def _clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str or not value or value != value.strip():
        _fail(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        _fail(reason)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(reason)
    normalized = parsed.astimezone(UTC)
    if normalized.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        _fail(reason)
    return normalized


def _bounded_json_tree(value: object, *, reason: str) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    text_bytes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_PROFILED_WITNESS_JSON_NODES or depth > MAX_PROFILED_WITNESS_JSON_DEPTH:
            _fail(reason)
        if type(item) is dict:
            mapping = cast(dict[object, object], item)
            if len(mapping) > MAX_PROFILED_WITNESS_CONTAINER_ITEMS:
                _fail(reason)
            for key, child in mapping.items():
                if type(key) is not str or not key or not key.isascii():
                    _fail(reason)
                text_bytes += len(key.encode("ascii"))
                stack.append((child, depth + 1))
        elif type(item) is list:
            values = cast(list[object], item)
            if len(values) > MAX_PROFILED_WITNESS_CONTAINER_ITEMS:
                _fail(reason)
            stack.extend((child, depth + 1) for child in values)
        elif type(item) is str:
            if not item.isascii():
                _fail(reason)
            text_bytes += len(item.encode("ascii"))
        elif item is None or type(item) is bool:
            pass
        elif type(item) is int:
            if not -(2**63) <= item <= 2**63 - 1:
                _fail(reason)
        else:
            _fail(reason)
        if text_bytes > MAX_PROFILED_WITNESS_TEXT_BYTES:
            _fail(reason)


def _canonical_json_bytes(
    value: object,
    *,
    reason: str,
    maximum_bytes: int = MAX_PROFILED_WITNESS_WIRE_BYTES,
) -> bytes:
    _bounded_json_tree(value, reason=reason)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise ProfiledTrainingExternalWitnessClientV1Error(reason) from exc
    if not encoded or len(encoded) > maximum_bytes:
        _fail(reason)
    return encoded


def _preflight_json_structure(payload: bytes, *, reason: str) -> None:
    """Bound JSON structure before the standard decoder allocates its tree."""

    depth = 0
    structural_tokens = 1
    in_string = False
    escaped = False
    for byte in payload:
        if byte > 0x7F:
            _fail(reason)
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:  # backslash
                escaped = True
            elif byte == 0x22:  # double quote
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in {0x7B, 0x5B}:  # { [
            depth += 1
            structural_tokens += 1
            if depth > MAX_PROFILED_WITNESS_JSON_DEPTH:
                _fail(reason)
        elif byte in {0x7D, 0x5D}:  # } ]
            depth -= 1
            if depth < 0:
                _fail(reason)
        elif byte in {0x2C, 0x3A}:  # , :
            structural_tokens += 1
        if structural_tokens > MAX_PROFILED_WITNESS_JSON_NODES:
            _fail(reason)
    if in_string or escaped or depth != 0:
        _fail(reason)


def _parse_exact_json(raw: object, *, reason: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_PROFILED_WITNESS_WIRE_BYTES:
        _fail(reason)
    payload = bytes(raw)
    _preflight_json_structure(payload, reason=reason)

    def reject_constant(_value: str) -> NoReturn:
        _fail(reason)

    def reject_float(_value: str) -> NoReturn:
        _fail(reason)

    def parse_integer(value: str) -> int:
        digits = value[1:] if value.startswith("-") else value
        if not digits or len(digits) > 19:
            _fail(reason)
        try:
            parsed = int(value)
        except ValueError:
            _fail(reason)
        if not -(2**63) <= parsed <= 2**63 - 1:
            _fail(reason)
        return parsed

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _fail(reason)
            result[key] = value
        return result

    try:
        text = payload.decode("ascii", errors="strict")
        parsed = json.loads(
            text,
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
            parse_float=reject_float,
            parse_int=parse_integer,
        )
    except ProfiledTrainingExternalWitnessClientV1Error:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ProfiledTrainingExternalWitnessClientV1Error(reason) from exc
    if type(parsed) is not dict:
        _fail(reason)
    result = cast(dict[str, Any], parsed)
    if not hmac.compare_digest(
        _canonical_json_bytes(result, reason=reason),
        payload,
    ):
        _fail(reason)
    return result


def _decode_base64(
    value: object,
    *,
    expected_byte_count: object,
    maximum_bytes: int,
    reason: str,
) -> bytes:
    if type(value) is not str or not value or not value.isascii():
        _fail(reason)
    count = _positive_integer(expected_byte_count, reason=reason)
    if count > maximum_bytes:
        _fail(reason)
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, TypeError):
        _fail(reason)
    if (
        len(decoded) != count
        or len(decoded) > maximum_bytes
        or base64.b64encode(decoded).decode("ascii") != value
    ):
        _fail(reason)
    return decoded


def _public_key(value: object, *, expected_sha256: object) -> tuple[Ed25519PublicKey, str]:
    if type(value) is not bytes or len(value) != ED25519_PUBLIC_KEY_BYTES:
        _fail("PROFILED_WITNESS_PUBLIC_KEY_INVALID")
    if not _valid_sha256(expected_sha256):
        _fail("PROFILED_WITNESS_PUBLIC_KEY_FINGERPRINT_INVALID")
    raw = bytes(value)
    digest = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(digest, cast(str, expected_sha256)):
        _fail("PROFILED_WITNESS_PUBLIC_KEY_FINGERPRINT_MISMATCH")
    try:
        return Ed25519PublicKey.from_public_bytes(raw), digest
    except ValueError:
        _fail("PROFILED_WITNESS_PUBLIC_KEY_INVALID")


def _verify_signature(
    material: Mapping[str, Any],
    *,
    public_key: Ed25519PublicKey,
    expected_domain: str,
    reason: str,
) -> dict[str, Any]:
    signature_hex = material.get("signature_hex")
    if type(signature_hex) is not str or _SIGNATURE_RE.fullmatch(signature_hex) is None:
        _fail(reason)
    unsigned = {key: value for key, value in material.items() if key != "signature_hex"}
    try:
        public_key.verify(
            bytes.fromhex(signature_hex),
            expected_domain.encode("ascii")
            + b"\0"
            + _canonical_json_bytes(unsigned, reason=reason),
        )
    except (InvalidSignature, TypeError, ValueError):
        _fail(reason)
    return unsigned


@dataclass(frozen=True, slots=True)
class ProfiledTrainingExternalWitnessWireResponseV1:
    status_code: int
    content_type: str
    body: bytes

    def __post_init__(self) -> None:
        if (
            type(self.status_code) is not int
            or not 100 <= self.status_code <= 599
            or type(self.content_type) is not str
            or type(self.body) is not bytes
            or len(self.body) > MAX_PROFILED_WITNESS_WIRE_BYTES
        ):
            _fail("PROFILED_WITNESS_TRANSPORT_RESPONSE_INVALID")


@dataclass(frozen=True, slots=True)
class _VerifiedProfiledWitnessEventV1:
    event: ProfiledTrainingObservationExternalWitnessEventV1
    signed_at: str
    signed_envelope_sha256: str
    signed_envelope_bytes: bytes


@runtime_checkable
class ProfiledTrainingExternalWitnessWireTransportV1(Protocol):
    def request(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None,
        idempotency_key: str | None,
    ) -> ProfiledTrainingExternalWitnessWireResponseV1: ...


class ProfiledTrainingExternalWitnessHttpsTransportV1:
    """No-redirect HTTPS transport with identity-encoded bounded bodies."""

    __slots__ = ("_authorization_header", "_base_url", "_client")

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str,
        timeout_seconds: float,
        _test_http_transport: httpx.MockTransport | None = None,
    ) -> None:
        if type(base_url) is not str or not base_url or base_url != base_url.strip():
            _fail("PROFILED_WITNESS_BASE_URL_INVALID")
        try:
            parsed = urlsplit(base_url)
            parsed_port = parsed.port
        except ValueError:
            _fail("PROFILED_WITNESS_BASE_URL_INVALID")
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
            or _SAFE_BASE_PATH_RE.fullmatch(parsed.path.rstrip("/")) is None
            or ".." in parsed.path.split("/")
        ):
            _fail("PROFILED_WITNESS_BASE_URL_INVALID")
        normalized_path = parsed.path.rstrip("/")
        normalized = urlunsplit(("https", parsed.netloc, normalized_path, "", ""))
        if type(bearer_token) is not str or _BEARER_TOKEN_RE.fullmatch(bearer_token) is None:
            _fail("PROFILED_WITNESS_BEARER_CREDENTIAL_INVALID")
        if (
            type(timeout_seconds) not in {int, float}
            or not MIN_PROFILED_WITNESS_TIMEOUT_SECONDS
            <= float(timeout_seconds)
            <= MAX_PROFILED_WITNESS_TIMEOUT_SECONDS
        ):
            _fail("PROFILED_WITNESS_TIMEOUT_INVALID")
        # Production has no arbitrary transport injection seam.  The exact
        # MockTransport type is admitted solely for deterministic unit tests.
        if _test_http_transport is not None and type(_test_http_transport) is not (
            httpx.MockTransport
        ):
            _fail("PROFILED_WITNESS_TEST_TRANSPORT_INVALID")
        self._base_url = normalized
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

    def __enter__(self) -> ProfiledTrainingExternalWitnessHttpsTransportV1:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def request(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None,
        idempotency_key: str | None,
    ) -> ProfiledTrainingExternalWitnessWireResponseV1:
        if method not in {"GET", "POST"}:
            _fail("PROFILED_WITNESS_HTTP_METHOD_INVALID")
        if (
            type(path) is not str
            or not path.startswith("/")
            or "//" in path
            or ".." in path.split("/")
            or "?" in path
            or "#" in path
        ):
            _fail("PROFILED_WITNESS_HTTP_PATH_INVALID")
        if body is not None and (
            type(body) is not bytes or not body or len(body) > MAX_PROFILED_WITNESS_WIRE_BYTES
        ):
            _fail("PROFILED_WITNESS_HTTP_BODY_INVALID")
        if method == "GET" and body is not None:
            _fail("PROFILED_WITNESS_HTTP_GET_BODY_FORBIDDEN")
        if idempotency_key is not None and not _valid_sha256(idempotency_key):
            _fail("PROFILED_WITNESS_IDEMPOTENCY_KEY_INVALID")
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Authorization": self._authorization_header,
            "User-Agent": "ai-bot-v2-profiled-witness-client/1",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        try:
            with self._client.stream(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                content=body,
                follow_redirects=False,
            ) as response:
                content_encoding = str(response.headers.get("content-encoding", ""))
                if content_encoding.strip().lower() not in {"", "identity"}:
                    _fail("PROFILED_WITNESS_HTTP_CONTENT_ENCODING_INVALID")
                payload = bytearray()
                for chunk in response.iter_raw():
                    if len(payload) + len(chunk) > MAX_PROFILED_WITNESS_WIRE_BYTES:
                        _fail("PROFILED_WITNESS_HTTP_RESPONSE_TOO_LARGE")
                    payload.extend(chunk)
                content_type = str(response.headers.get("content-type", ""))
                result = ProfiledTrainingExternalWitnessWireResponseV1(
                    status_code=int(response.status_code),
                    content_type=content_type,
                    body=bytes(payload),
                )
        except ProfiledTrainingExternalWitnessClientV1Error:
            raise
        except httpx.HTTPError as exc:
            raise ProfiledTrainingExternalWitnessClientV1Error(
                f"PROFILED_WITNESS_HTTP_TRANSPORT_FAILED:{type(exc).__name__}"
            ) from exc
        if result.body and result.content_type.split(";", 1)[0].strip().lower() != (
            "application/json"
        ):
            _fail("PROFILED_WITNESS_HTTP_CONTENT_TYPE_INVALID")
        return result


class PinnedProfiledTrainingExternalWitnessClientV1(
    ProfiledTrainingObservationExternalWitnessV1
):
    """Signed witness client with reverified durable-anchor restore support."""

    __slots__ = (
        "_close_transport_on_close",
        "_closed",
        "_head_lock",
        "_observed_heads",
        "_public_key",
        "_public_key_sha256",
        "_transport",
        "_witness_id",
    )

    def __init__(
        self,
        *,
        transport: ProfiledTrainingExternalWitnessWireTransportV1,
        witness_id: str,
        witness_public_key_bytes: bytes,
        expected_witness_public_key_sha256: str,
        trusted_head_envelope_bytes_by_namespace: Mapping[str, bytes] | None = None,
        close_transport_on_close: bool = False,
    ) -> None:
        if not isinstance(transport, ProfiledTrainingExternalWitnessWireTransportV1):
            _fail("PROFILED_WITNESS_TRANSPORT_CONTRACT_INVALID")
        if type(close_transport_on_close) is not bool or (
            close_transport_on_close and not callable(getattr(transport, "close", None))
        ):
            _fail("PROFILED_WITNESS_TRANSPORT_OWNERSHIP_INVALID")
        self._transport = transport
        self._close_transport_on_close = close_transport_on_close
        self._closed = False
        self._witness_id = _identifier(
            witness_id,
            reason="PROFILED_WITNESS_ID_INVALID",
        )
        self._public_key, self._public_key_sha256 = _public_key(
            witness_public_key_bytes,
            expected_sha256=expected_witness_public_key_sha256,
        )
        self._head_lock = threading.Lock()
        self._observed_heads: dict[str, tuple[int, str, str, str, str, bytes]] = {}
        if trusted_head_envelope_bytes_by_namespace is not None:
            if not isinstance(trusted_head_envelope_bytes_by_namespace, Mapping):
                _fail("PROFILED_WITNESS_TRUSTED_HEADS_INVALID")
            for namespace, envelope_bytes in trusted_head_envelope_bytes_by_namespace.items():
                namespace_text = _identifier(
                    namespace,
                    reason="PROFILED_WITNESS_TRUSTED_HEAD_NAMESPACE_INVALID",
                )
                verified = self._verified_event(
                    ProfiledTrainingExternalWitnessWireResponseV1(
                        status_code=200,
                        content_type="application/json",
                        body=envelope_bytes,
                    ),
                    expected_namespace=namespace_text,
                    expected_sequence=None,
                )
                event = verified.event
                self._observed_heads[namespace_text] = (
                    event.sequence,
                    event.previous_event_sha256,
                    event.event_sha256,
                    verified.signed_at,
                    verified.signed_envelope_sha256,
                    verified.signed_envelope_bytes,
                )

    @property
    def witness_id(self) -> str:
        return self._witness_id

    @property
    def witness_public_key_sha256(self) -> str:
        return self._public_key_sha256

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._close_transport_on_close:
            cast(Any, self._transport).close()

    def __enter__(self) -> PinnedProfiledTrainingExternalWitnessClientV1:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def trusted_head_envelope_bytes(self, *, namespace: str) -> bytes:
        """Return the exact verified head envelope for durable caller anchoring."""

        namespace_text = _identifier(
            namespace,
            reason="PROFILED_WITNESS_NAMESPACE_INVALID",
        )
        with self._head_lock:
            observed = self._observed_heads.get(namespace_text)
            if observed is None:
                _fail("PROFILED_WITNESS_TRUSTED_HEAD_UNAVAILABLE")
            return bytes(observed[5])

    def _path(self, namespace: str, suffix: str) -> str:
        return f"/namespaces/{quote(namespace, safe='')}/{suffix}"

    def _verified_event(
        self,
        response: ProfiledTrainingExternalWitnessWireResponseV1,
        *,
        expected_namespace: str,
        expected_sequence: int | None,
    ) -> _VerifiedProfiledWitnessEventV1:
        if response.status_code != 200:
            _fail("PROFILED_WITNESS_EVENT_HTTP_STATUS_INVALID")
        material = _parse_exact_json(
            response.body,
            reason="PROFILED_WITNESS_EVENT_JSON_INVALID",
        )
        if set(material) != _EVENT_FIELDS:
            _fail("PROFILED_WITNESS_EVENT_FIELD_SET_INVALID")
        unsigned = _verify_signature(
            material,
            public_key=self._public_key,
            expected_domain=PROFILED_WITNESS_WIRE_EVENT_SIGNATURE_DOMAIN,
            reason="PROFILED_WITNESS_EVENT_SIGNATURE_UNVERIFIED",
        )
        sequence = _positive_integer(
            unsigned.get("sequence"),
            reason="PROFILED_WITNESS_EVENT_SEQUENCE_INVALID",
        )
        event_bytes = _decode_base64(
            unsigned.get("event_base64"),
            expected_byte_count=unsigned.get("event_byte_count"),
            maximum_bytes=MAX_PROFILED_OBSERVATION_HEAD_EVENT_BYTES,
            reason="PROFILED_WITNESS_EVENT_PAYLOAD_INVALID",
        )
        event_sha256 = hashlib.sha256(event_bytes).hexdigest()
        if (
            unsigned.get("schema_version")
            != PROFILED_WITNESS_WIRE_EVENT_V1_SCHEMA_VERSION
            or unsigned.get("signature_algorithm")
            != PROFILED_WITNESS_WIRE_SIGNATURE_ALGORITHM
            or unsigned.get("signature_domain")
            != PROFILED_WITNESS_WIRE_EVENT_SIGNATURE_DOMAIN
            or unsigned.get("witness_id") != self._witness_id
            or unsigned.get("namespace") != expected_namespace
            or (expected_sequence is not None and sequence != expected_sequence)
            or not _valid_sha256(unsigned.get("previous_event_sha256"))
            or unsigned.get("event_sha256") != event_sha256
        ):
            _fail("PROFILED_WITNESS_EVENT_BINDING_INVALID")
        signed_at = cast(str, unsigned.get("signed_at"))
        _clock(signed_at, reason="PROFILED_WITNESS_EVENT_CLOCK_INVALID")
        return _VerifiedProfiledWitnessEventV1(
            event=ProfiledTrainingObservationExternalWitnessEventV1(
                schema_version=PROFILED_OBSERVATION_WITNESS_EVENT_V1_SCHEMA_VERSION,
                witness_id=self._witness_id,
                namespace=expected_namespace,
                sequence=sequence,
                previous_event_sha256=cast(str, unsigned["previous_event_sha256"]),
                event_sha256=event_sha256,
                event_bytes=event_bytes,
            ),
            signed_at=signed_at,
            signed_envelope_sha256=hashlib.sha256(response.body).hexdigest(),
            signed_envelope_bytes=bytes(response.body),
        )

    def _read_verified_event(
        self,
        *,
        namespace: str,
        sequence: int,
    ) -> _VerifiedProfiledWitnessEventV1:
        response = self._transport.request(
            method="GET",
            path=self._path(namespace, f"events/{sequence}"),
            body=None,
            idempotency_key=None,
        )
        return self._verified_event(
            response,
            expected_namespace=namespace,
            expected_sequence=sequence,
        )

    def _validate_chain_segment(
        self,
        *,
        latest: _VerifiedProfiledWitnessEventV1,
        first_sequence: int,
        expected_previous_event_sha256: str,
    ) -> None:
        final_sequence = latest.event.sequence
        count = final_sequence - first_sequence + 1
        if count <= 0 or count > MAX_PROFILED_WITNESS_BOOTSTRAP_EVENTS:
            _fail("PROFILED_WITNESS_SIGNED_HEAD_BOOTSTRAP_LIMIT_EXCEEDED")
        previous_sha256 = expected_previous_event_sha256
        for sequence in range(first_sequence, final_sequence + 1):
            verified = (
                latest
                if sequence == final_sequence
                else self._read_verified_event(namespace=latest.event.namespace, sequence=sequence)
            )
            if verified.event.previous_event_sha256 != previous_sha256:
                _fail("PROFILED_WITNESS_SIGNED_HEAD_CHAIN_INVALID")
            previous_sha256 = verified.event.event_sha256

    def _observe_head(self, verified: _VerifiedProfiledWitnessEventV1) -> None:
        event = verified.event
        candidate = (
            event.sequence,
            event.previous_event_sha256,
            event.event_sha256,
            verified.signed_at,
            verified.signed_envelope_sha256,
            verified.signed_envelope_bytes,
        )
        while True:
            with self._head_lock:
                previous = self._observed_heads.get(event.namespace)
            if previous is None:
                first_sequence = 1
                expected_previous_event_sha256 = (
                    PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256
                )
            else:
                (
                    previous_sequence,
                    previous_previous_sha256,
                    previous_event_sha256,
                    previous_signed_at,
                    previous_envelope_sha256,
                    previous_envelope_bytes,
                ) = previous
                if event.sequence < previous_sequence:
                    _fail("PROFILED_WITNESS_SIGNED_HEAD_ROLLBACK")
                if event.sequence == previous_sequence:
                    if (
                        event.previous_event_sha256 != previous_previous_sha256
                        or event.event_sha256 != previous_event_sha256
                        or verified.signed_at != previous_signed_at
                        or verified.signed_envelope_sha256 != previous_envelope_sha256
                        or not hmac.compare_digest(
                            verified.signed_envelope_bytes,
                            previous_envelope_bytes,
                        )
                    ):
                        _fail("PROFILED_WITNESS_SIGNED_HEAD_FORK")
                    return
                first_sequence = previous_sequence + 1
                expected_previous_event_sha256 = previous_event_sha256
            self._validate_chain_segment(
                latest=verified,
                first_sequence=first_sequence,
                expected_previous_event_sha256=expected_previous_event_sha256,
            )
            with self._head_lock:
                if self._observed_heads.get(event.namespace) != previous:
                    continue
                self._observed_heads[event.namespace] = candidate
                return

    def read_latest(
        self,
        *,
        namespace: str,
    ) -> ProfiledTrainingObservationExternalWitnessEventV1 | None:
        namespace_text = _identifier(
            namespace,
            reason="PROFILED_WITNESS_NAMESPACE_INVALID",
        )
        response = self._transport.request(
            method="GET",
            path=self._path(namespace_text, "latest"),
            body=None,
            idempotency_key=None,
        )
        if response.status_code == 404:
            if response.body:
                _fail("PROFILED_WITNESS_GENESIS_RESPONSE_BODY_FORBIDDEN")
            with self._head_lock:
                if namespace_text in self._observed_heads:
                    _fail("PROFILED_WITNESS_SIGNED_HEAD_ROLLBACK")
            _fail("PROFILED_WITNESS_UNSIGNED_ABSENCE_FORBIDDEN")
        verified = self._verified_event(
            response,
            expected_namespace=namespace_text,
            expected_sequence=None,
        )
        self._observe_head(verified)
        return verified.event

    def read_event(
        self,
        *,
        namespace: str,
        sequence: int,
    ) -> ProfiledTrainingObservationExternalWitnessEventV1:
        namespace_text = _identifier(
            namespace,
            reason="PROFILED_WITNESS_NAMESPACE_INVALID",
        )
        expected_sequence = _positive_integer(
            sequence,
            reason="PROFILED_WITNESS_EVENT_SEQUENCE_INVALID",
        )
        return self._read_verified_event(
            namespace=namespace_text,
            sequence=expected_sequence,
        ).event

    def _receipt(
        self,
        response: ProfiledTrainingExternalWitnessWireResponseV1,
        *,
        expected_namespace: str,
        expected_sequence: int,
        expected_previous_event_sha256: str,
        expected_event_sha256: str,
        expected_request_sha256: str,
        expected_idempotency_key: str,
    ) -> ProfiledTrainingObservationExternalWitnessAppendReceiptV1:
        if response.status_code not in {200, 201}:
            if response.status_code == 409:
                _fail("PROFILED_WITNESS_COMPARE_AND_APPEND_CONFLICT")
            _fail("PROFILED_WITNESS_APPEND_HTTP_STATUS_INVALID")
        material = _parse_exact_json(
            response.body,
            reason="PROFILED_WITNESS_RECEIPT_JSON_INVALID",
        )
        if set(material) != _RECEIPT_FIELDS:
            _fail("PROFILED_WITNESS_RECEIPT_FIELD_SET_INVALID")
        unsigned = _verify_signature(
            material,
            public_key=self._public_key,
            expected_domain=PROFILED_WITNESS_WIRE_RECEIPT_SIGNATURE_DOMAIN,
            reason="PROFILED_WITNESS_RECEIPT_SIGNATURE_UNVERIFIED",
        )
        receipt_bytes = _decode_base64(
            unsigned.get("receipt_payload_base64"),
            expected_byte_count=unsigned.get("receipt_payload_byte_count"),
            maximum_bytes=MAX_PROFILED_WITNESS_RECEIPT_PAYLOAD_BYTES,
            reason="PROFILED_WITNESS_RECEIPT_PAYLOAD_INVALID",
        )
        receipt_payload_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
        receipt_sequence = _positive_integer(
            unsigned.get("sequence"),
            reason="PROFILED_WITNESS_RECEIPT_SEQUENCE_INVALID",
        )
        if (
            unsigned.get("schema_version")
            != PROFILED_WITNESS_WIRE_APPEND_RECEIPT_V1_SCHEMA_VERSION
            or unsigned.get("signature_algorithm")
            != PROFILED_WITNESS_WIRE_SIGNATURE_ALGORITHM
            or unsigned.get("signature_domain")
            != PROFILED_WITNESS_WIRE_RECEIPT_SIGNATURE_DOMAIN
            or unsigned.get("witness_id") != self._witness_id
            or unsigned.get("namespace") != expected_namespace
            or receipt_sequence != expected_sequence
            or unsigned.get("previous_event_sha256")
            != expected_previous_event_sha256
            or unsigned.get("event_sha256") != expected_event_sha256
            or unsigned.get("request_sha256") != expected_request_sha256
            or unsigned.get("idempotency_key") != expected_idempotency_key
            or unsigned.get("receipt_payload_sha256") != receipt_payload_sha256
        ):
            _fail("PROFILED_WITNESS_RECEIPT_BINDING_INVALID")
        accepted_at = cast(str, unsigned.get("accepted_at"))
        _clock(accepted_at, reason="PROFILED_WITNESS_RECEIPT_CLOCK_INVALID")
        signed_receipt_bytes = bytes(response.body)
        return ProfiledTrainingObservationExternalWitnessAppendReceiptV1(
            schema_version=PROFILED_OBSERVATION_WITNESS_RECEIPT_V1_SCHEMA_VERSION,
            witness_id=self._witness_id,
            namespace=expected_namespace,
            sequence=expected_sequence,
            previous_event_sha256=expected_previous_event_sha256,
            event_sha256=expected_event_sha256,
            accepted_at=accepted_at,
            receipt_sha256=hashlib.sha256(signed_receipt_bytes).hexdigest(),
            receipt_bytes=signed_receipt_bytes,
        )

    def verify_append_receipt_envelope(
        self,
        *,
        signed_receipt_envelope_bytes: bytes,
        expected_namespace: str,
        expected_sequence: int,
        expected_previous_event_sha256: str,
        expected_event_sha256: str,
        expected_request_sha256: str,
        expected_idempotency_key: str,
    ) -> ProfiledTrainingObservationExternalWitnessAppendReceiptV1:
        """Reverify exact persisted signed receipt evidence after a restart."""

        namespace = _identifier(
            expected_namespace,
            reason="PROFILED_WITNESS_NAMESPACE_INVALID",
        )
        sequence = _positive_integer(
            expected_sequence,
            reason="PROFILED_WITNESS_RECEIPT_SEQUENCE_INVALID",
        )
        for value, reason in (
            (
                expected_previous_event_sha256,
                "PROFILED_WITNESS_EXPECTED_EVENT_SHA256_INVALID",
            ),
            (expected_event_sha256, "PROFILED_WITNESS_EVENT_SHA256_INVALID"),
            (expected_request_sha256, "PROFILED_WITNESS_REQUEST_SHA256_INVALID"),
            (expected_idempotency_key, "PROFILED_WITNESS_IDEMPOTENCY_KEY_INVALID"),
        ):
            if not _valid_sha256(value):
                _fail(reason)
        return self._receipt(
            ProfiledTrainingExternalWitnessWireResponseV1(
                status_code=200,
                content_type="application/json",
                body=signed_receipt_envelope_bytes,
            ),
            expected_namespace=namespace,
            expected_sequence=sequence,
            expected_previous_event_sha256=expected_previous_event_sha256,
            expected_event_sha256=expected_event_sha256,
            expected_request_sha256=expected_request_sha256,
            expected_idempotency_key=expected_idempotency_key,
        )

    def compare_and_append(
        self,
        *,
        namespace: str,
        expected_sequence: int,
        expected_event_sha256: str,
        event_bytes: bytes,
    ) -> ProfiledTrainingObservationExternalWitnessAppendReceiptV1:
        """CAS one event; callers must retry ambiguous delivery with identical inputs."""

        namespace_text = _identifier(
            namespace,
            reason="PROFILED_WITNESS_NAMESPACE_INVALID",
        )
        prior_sequence = _positive_integer(
            expected_sequence,
            reason="PROFILED_WITNESS_EXPECTED_SEQUENCE_INVALID",
            allow_zero=True,
        )
        if not _valid_sha256(expected_event_sha256):
            _fail("PROFILED_WITNESS_EXPECTED_EVENT_SHA256_INVALID")
        if (
            type(event_bytes) is not bytes
            or not event_bytes
            or len(event_bytes) > MAX_PROFILED_OBSERVATION_HEAD_EVENT_BYTES
        ):
            _fail("PROFILED_WITNESS_APPEND_EVENT_BYTES_INVALID")

        if (
            prior_sequence == 0
            and expected_event_sha256
            != PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256
        ):
            _fail("PROFILED_WITNESS_EXPECTED_GENESIS_MISMATCH")

        event_payload = bytes(event_bytes)
        event_sha256 = hashlib.sha256(event_payload).hexdigest()
        base_request = {
            "schema_version": PROFILED_WITNESS_COMPARE_APPEND_REQUEST_V1_SCHEMA_VERSION,
            "request_domain": PROFILED_WITNESS_COMPARE_APPEND_REQUEST_DOMAIN,
            "witness_id": self._witness_id,
            "namespace": namespace_text,
            "expected_sequence": prior_sequence,
            "expected_event_sha256": expected_event_sha256,
            "event_sha256": event_sha256,
            "event_byte_count": len(event_payload),
            "event_base64": base64.b64encode(event_payload).decode("ascii"),
            "optimizer_admission_authorized": False,
            "checkpoint_write_authorized": False,
            "prediction_authorized": False,
            "paper_trading_authorized": False,
            "live_execution_authorized": False,
            "order_submission_authorized": False,
            "runtime_wired": False,
        }
        idempotency_key = hashlib.sha256(
            PROFILED_WITNESS_COMPARE_APPEND_REQUEST_DOMAIN.encode("ascii")
            + b"\0"
            + _canonical_json_bytes(
                base_request,
                reason="PROFILED_WITNESS_APPEND_REQUEST_JSON_INVALID",
            )
        ).hexdigest()
        request_material = {**base_request, "idempotency_key": idempotency_key}
        request_bytes = _canonical_json_bytes(
            request_material,
            reason="PROFILED_WITNESS_APPEND_REQUEST_JSON_INVALID",
        )
        request_sha256 = hashlib.sha256(request_bytes).hexdigest()
        response = self._transport.request(
            method="POST",
            path=self._path(namespace_text, "events:compare-and-append"),
            body=request_bytes,
            idempotency_key=idempotency_key,
        )
        receipt = self._receipt(
            response,
            expected_namespace=namespace_text,
            expected_sequence=prior_sequence + 1,
            expected_previous_event_sha256=expected_event_sha256,
            expected_event_sha256=event_sha256,
            expected_request_sha256=request_sha256,
            expected_idempotency_key=idempotency_key,
        )
        readback = self.read_event(
            namespace=namespace_text,
            sequence=receipt.sequence,
        )
        if (
            readback.previous_event_sha256 != expected_event_sha256
            or readback.event_sha256 != event_sha256
            or not hmac.compare_digest(readback.event_bytes, event_payload)
        ):
            _fail("PROFILED_WITNESS_APPEND_EVENT_READBACK_MISMATCH")
        latest_after = self.read_latest(namespace=namespace_text)
        if (
            latest_after is None
            or latest_after.sequence != receipt.sequence
            or latest_after.event_sha256 != receipt.event_sha256
        ):
            _fail("PROFILED_WITNESS_APPEND_LATEST_READBACK_MISMATCH")
        return receipt


__all__ = (
    "MAX_PROFILED_WITNESS_BOOTSTRAP_EVENTS",
    "MAX_PROFILED_WITNESS_RECEIPT_PAYLOAD_BYTES",
    "MAX_PROFILED_WITNESS_WIRE_BYTES",
    "PROFILED_WITNESS_COMPARE_APPEND_REQUEST_DOMAIN",
    "PROFILED_WITNESS_COMPARE_APPEND_REQUEST_V1_SCHEMA_VERSION",
    "PROFILED_WITNESS_WIRE_APPEND_RECEIPT_V1_SCHEMA_VERSION",
    "PROFILED_WITNESS_WIRE_EVENT_SIGNATURE_DOMAIN",
    "PROFILED_WITNESS_WIRE_EVENT_V1_SCHEMA_VERSION",
    "PROFILED_WITNESS_WIRE_RECEIPT_SIGNATURE_DOMAIN",
    "PinnedProfiledTrainingExternalWitnessClientV1",
    "ProfiledTrainingExternalWitnessClientV1Error",
    "ProfiledTrainingExternalWitnessHttpsTransportV1",
    "ProfiledTrainingExternalWitnessWireResponseV1",
    "ProfiledTrainingExternalWitnessWireTransportV1",
)
