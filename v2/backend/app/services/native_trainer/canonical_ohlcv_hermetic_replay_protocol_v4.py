"""Dormant canonical wire contracts for hermetic OHLCV semantic replay.

This module owns only two bounded, canonical-JSON protocol documents:

* a replay request containing content addresses and decision correlation data;
* a separate policy-channel frame containing supervisor-supplied verifier
  coordinates and the exact policy bytes encoded as canonical base64.

The request cannot carry a policy, filesystem root, Python path, code closure,
resource policy, or authority field.  Policy-channel validation proves only
that the frame is exact, canonical, internally hash-bound, and preserves the
embedded bytes.  It does not prove that the channel is sealed, immutable, or
supervisor-authenticated.  Those are future process-boundary responsibilities.

There is deliberately no process launch, filesystem access, network access,
Redis access, trainer invocation, or trading action here.  The fixed limits
are parser and transport resource ceilings, not market or risk thresholds.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, NoReturn, cast

CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_CONTRACT_VERSION = (
    "canonical_ohlcv_hermetic_replay_protocol_contract_v4"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_SCHEMA_VERSION = (
    "canonical_ohlcv_hermetic_replay_request_v4"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_CHANNEL_V4_SCHEMA_VERSION = (
    "canonical_ohlcv_hermetic_replay_policy_channel_v4"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_DOMAIN_SEPARATOR = (
    b"v2/native-trainer/canonical-ohlcv-hermetic-replay-request/v4\0"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_CHANNEL_V4_DOMAIN_SEPARATOR = (
    b"v2/native-trainer/canonical-ohlcv-hermetic-replay-policy-channel/v4\0"
)

SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION_V4 = "source_payload_content_address_v1"
SUPPORTED_HERMETIC_REPLAY_TIMEFRAMES_V4 = ("1m", "5m", "15m", "1h", "4h")

MAX_HERMETIC_REPLAY_REQUEST_BYTES_V4 = 64 * 1024
MAX_HERMETIC_REPLAY_POLICY_DOCUMENT_BYTES_V4 = 128 * 1024
MAX_HERMETIC_REPLAY_POLICY_CHANNEL_BYTES_V4 = 192 * 1024
MAX_HERMETIC_REPLAY_MANIFEST_BYTES_V4 = 8 * 1024 * 1024
MAX_HERMETIC_REPLAY_SELECTED_ROW_BYTES_V4 = 64 * 1024
MAX_HERMETIC_REPLAY_JSON_DEPTH_V4 = 8
MAX_HERMETIC_REPLAY_REQUEST_JSON_NODES_V4 = 64
MAX_HERMETIC_REPLAY_POLICY_CHANNEL_JSON_NODES_V4 = 32
MAX_HERMETIC_REPLAY_JSON_CONTAINER_ITEMS_V4 = 32
MAX_HERMETIC_REPLAY_REQUEST_TEXT_BYTES_V4 = 16 * 1024
MAX_HERMETIC_REPLAY_POLICY_CHANNEL_TEXT_BYTES_V4 = 190 * 1024
MAX_HERMETIC_REPLAY_REQUEST_STRING_BYTES_V4 = 4096
MAX_HERMETIC_REPLAY_POLICY_BASE64_BYTES_V4 = (
    (MAX_HERMETIC_REPLAY_POLICY_DOCUMENT_BYTES_V4 + 2) // 3
) * 4
MAX_HERMETIC_REPLAY_IDENTIFIER_BYTES_V4 = 128
MAX_HERMETIC_REPLAY_PATH_BYTES_V4 = 4096

_MIN_SIGNED_64 = -(2**63)
_MAX_SIGNED_64 = 2**63 - 1
_CLOCK_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_NONCE_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$", re.ASCII)
_POLICY_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$", re.ASCII)
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$", re.ASCII)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$", re.ASCII)

_ADDRESS_FIELDS = frozenset(
    {"schema_version", "payload_sha256", "payload_byte_count", "relative_path"}
)
_REQUEST_MATERIAL_FIELDS = frozenset(
    {
        "schema_version",
        "contract_version",
        "request_nonce",
        "run_id",
        "cycle_id",
        "decision_id",
        "manifest_address",
        "selected_row_address",
        "symbol",
        "timeframe",
        "decision_time",
    }
)
_REQUEST_FIELDS = _REQUEST_MATERIAL_FIELDS | {"request_sha256"}
_POLICY_CHANNEL_MATERIAL_FIELDS = frozenset(
    {
        "schema_version",
        "contract_version",
        "expected_policy_sha256",
        "expected_registry_id",
        "expected_registry_version",
        "expected_policy_id",
        "expected_policy_revision",
        "policy_document_base64",
    }
)
_POLICY_CHANNEL_FIELDS = _POLICY_CHANNEL_MATERIAL_FIELDS | {"policy_channel_sha256"}

# Exact request-field matching already rejects every unknown key.  This set
# gives policy-boundary violations a stable, explicit fail-closed reason.
FORBIDDEN_HERMETIC_REPLAY_REQUEST_FIELDS_V4 = frozenset(
    {
        "accepted_schemas",
        "atomic_transport_authenticated",
        "audit_only",
        "authority",
        "authority_policy",
        "canonical_profile",
        "cas_root",
        "code_closure",
        "consumer_eligible",
        "dependency_manifest_bound",
        "durable_ledger_membership_verified",
        "expected_policy_id",
        "expected_policy_revision",
        "expected_policy_sha256",
        "expected_registry_id",
        "expected_registry_version",
        "factory_capture_authenticated",
        "feature_snapshot_published",
        "filesystem_writes_disabled",
        "ledger_owned_cas_root",
        "live_execution_authorized",
        "network_disabled",
        "paper_trading_authorized",
        "per_field_receipt_bound",
        "policy",
        "policy_channel",
        "policy_channel_fd",
        "policy_document",
        "policy_document_base64",
        "policy_id",
        "policy_revision",
        "policy_source_authenticated",
        "prediction_authorized",
        "project_root",
        "project_owner_uid",
        "python_path",
        "python_runtime",
        "resource_ceilings",
        "runtime_dependency_closure_verified",
        "runtime_sandbox_enforced",
        "runtime_wired",
        "source_finality_recomputed",
        "source_payload_authenticated",
        "source_payload_semantics_verified",
        "source_scope_complete",
        "trainer_admission_authorized",
        "upstream_producer_authenticated",
        "worker",
        "worker_path",
        "worker_protocol",
    }
)


class CanonicalOhlcvHermeticReplayProtocolV4Error(RuntimeError):
    """A bounded replay request or policy-channel frame failed closed."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _fail(reason: str) -> NoReturn:
    raise CanonicalOhlcvHermeticReplayProtocolV4Error(reason) from None


def _reject_json_constant(_value: str) -> NoReturn:
    _fail("hermetic_replay_protocol_json_constant_forbidden")


def _reject_json_float(_value: str) -> NoReturn:
    _fail("hermetic_replay_protocol_json_float_forbidden")


def _parse_json_int(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 19:
        _fail("hermetic_replay_protocol_json_integer_out_of_range")
    try:
        parsed = int(value)
    except ValueError:
        _fail("hermetic_replay_protocol_json_integer_out_of_range")
    if not _MIN_SIGNED_64 <= parsed <= _MAX_SIGNED_64:
        _fail("hermetic_replay_protocol_json_integer_out_of_range")
    return parsed


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("hermetic_replay_protocol_duplicate_json_key")
        result[key] = value
    return result


def _preflight_json_depth(document: bytes) -> None:
    depth = 0
    in_string = False
    escaped = False
    for byte in document:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x7B, 0x5B):
            depth += 1
            if depth > MAX_HERMETIC_REPLAY_JSON_DEPTH_V4:
                _fail("hermetic_replay_protocol_json_depth_limit_exceeded")
        elif byte in (0x7D, 0x5D):
            depth -= 1
            if depth < 0:
                _fail("hermetic_replay_protocol_json_invalid")


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("hermetic_replay_protocol_canonicalization_failed")


def _bounded_json_tree(
    value: object,
    *,
    max_nodes: int,
    max_text_bytes: int,
    max_string_bytes: int,
) -> None:
    nodes = 0
    total_text_bytes = 0

    def inspect(item: object, *, depth: int) -> None:
        nonlocal nodes, total_text_bytes
        nodes += 1
        if nodes > max_nodes:
            _fail("hermetic_replay_protocol_json_node_limit_exceeded")
        if depth > MAX_HERMETIC_REPLAY_JSON_DEPTH_V4:
            _fail("hermetic_replay_protocol_json_depth_limit_exceeded")
        if type(item) is dict:
            mapping = cast(dict[object, object], item)
            if len(mapping) > MAX_HERMETIC_REPLAY_JSON_CONTAINER_ITEMS_V4:
                _fail("hermetic_replay_protocol_json_container_limit_exceeded")
            for key, child in mapping.items():
                if type(key) is not str:
                    _fail("hermetic_replay_protocol_json_key_invalid")
                try:
                    encoded_key = key.encode("ascii", errors="strict")
                except UnicodeEncodeError:
                    _fail("hermetic_replay_protocol_non_ascii_text_forbidden")
                if (
                    not encoded_key
                    or len(encoded_key) > MAX_HERMETIC_REPLAY_REQUEST_STRING_BYTES_V4
                ):
                    _fail("hermetic_replay_protocol_json_key_invalid")
                total_text_bytes += len(encoded_key)
                if total_text_bytes > max_text_bytes:
                    _fail("hermetic_replay_protocol_json_text_limit_exceeded")
                inspect(child, depth=depth + 1)
            return
        if type(item) is list:
            sequence = cast(list[object], item)
            if len(sequence) > MAX_HERMETIC_REPLAY_JSON_CONTAINER_ITEMS_V4:
                _fail("hermetic_replay_protocol_json_container_limit_exceeded")
            for child in sequence:
                inspect(child, depth=depth + 1)
            return
        if type(item) is str:
            try:
                encoded = item.encode("ascii", errors="strict")
            except UnicodeEncodeError:
                _fail("hermetic_replay_protocol_non_ascii_text_forbidden")
            if len(encoded) > max_string_bytes:
                _fail("hermetic_replay_protocol_json_string_limit_exceeded")
            total_text_bytes += len(encoded)
            if total_text_bytes > max_text_bytes:
                _fail("hermetic_replay_protocol_json_text_limit_exceeded")
            return
        if type(item) is bool or item is None:
            return
        if type(item) is int:
            if not _MIN_SIGNED_64 <= item <= _MAX_SIGNED_64:
                _fail("hermetic_replay_protocol_json_integer_out_of_range")
            return
        _fail("hermetic_replay_protocol_json_primitive_type_invalid")

    inspect(value, depth=1)


def _parse_exact_canonical_object(
    document: object,
    *,
    max_document_bytes: int,
    max_nodes: int,
    max_text_bytes: int,
    max_string_bytes: int,
    kind: str,
) -> dict[str, object]:
    if type(document) is not bytes:
        _fail(f"hermetic_replay_protocol_{kind}_exact_bytes_required")
    exact_document = document
    if not 1 <= len(exact_document) <= max_document_bytes:
        _fail(f"hermetic_replay_protocol_{kind}_document_size_invalid")
    _preflight_json_depth(exact_document)
    try:
        parsed = json.loads(
            exact_document,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
            parse_float=_reject_json_float,
            parse_int=_parse_json_int,
        )
    except CanonicalOhlcvHermeticReplayProtocolV4Error:
        raise
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError, ValueError):
        _fail(f"hermetic_replay_protocol_{kind}_json_invalid")
    _bounded_json_tree(
        parsed,
        max_nodes=max_nodes,
        max_text_bytes=max_text_bytes,
        max_string_bytes=max_string_bytes,
    )
    if type(parsed) is not dict:
        _fail(f"hermetic_replay_protocol_{kind}_object_required")
    canonical = _canonical_json_bytes(parsed)
    if not hmac.compare_digest(canonical, exact_document):
        _fail(f"hermetic_replay_protocol_{kind}_noncanonical_json")
    return cast(dict[str, object], parsed)


def _require_exact_fields(
    value: object,
    expected: frozenset[str],
    *,
    reason: str,
) -> dict[str, object]:
    if type(value) is not dict:
        _fail(reason)
    mapping = cast(dict[object, object], value)
    try:
        items = tuple(mapping.items())
        observed_length = len(mapping)
    except RuntimeError:
        _fail(reason)
    if len(items) != observed_length:
        _fail(reason)
    snapshot: dict[str, object] = {}
    for key, item in items:
        if type(key) is not str or key in snapshot:
            _fail(reason)
        snapshot[key] = item
    if frozenset(snapshot) != expected:
        _fail(reason)
    return snapshot


def _require_exact_text(
    value: object,
    *,
    reason: str,
    maximum_bytes: int = MAX_HERMETIC_REPLAY_REQUEST_STRING_BYTES_V4,
) -> str:
    if type(value) is not str:
        _fail(reason)
    if len(value) > maximum_bytes:
        _fail(reason)
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        _fail(reason)
    if len(encoded) > maximum_bytes:
        _fail(reason)
    return value


def _require_pattern(value: object, pattern: re.Pattern[str], *, reason: str) -> str:
    text = _require_exact_text(value, reason=reason)
    if pattern.fullmatch(text) is None:
        _fail(reason)
    return text


def _require_sha256(value: object, *, reason: str) -> str:
    return _require_pattern(value, _SHA256_RE, reason=reason)


def _require_positive_int(value: object, *, maximum: int, reason: str) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        _fail(reason)
    return value


def _normalize_address(
    value: object,
    *,
    maximum_byte_count: int,
    reason: str,
) -> dict[str, object]:
    address = _require_exact_fields(value, _ADDRESS_FIELDS, reason=reason)
    schema_version = _require_exact_text(address["schema_version"], reason=reason)
    digest = _require_sha256(address["payload_sha256"], reason=reason)
    byte_count = _require_positive_int(
        address["payload_byte_count"],
        maximum=maximum_byte_count,
        reason=reason,
    )
    relative_path = _require_exact_text(address["relative_path"], reason=reason)
    if (
        schema_version != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION_V4
        or len(relative_path.encode("ascii")) > MAX_HERMETIC_REPLAY_PATH_BYTES_V4
        or relative_path != f"sha256/{digest[:2]}/{digest}"
    ):
        _fail(reason)
    return {
        "schema_version": schema_version,
        "payload_sha256": digest,
        "payload_byte_count": byte_count,
        "relative_path": relative_path,
    }


def _require_identifier(value: object, *, reason: str) -> str:
    text = _require_pattern(value, _IDENTIFIER_RE, reason=reason)
    if len(text.encode("ascii")) > MAX_HERMETIC_REPLAY_IDENTIFIER_BYTES_V4:
        _fail(reason)
    return text


def _require_decision_time(value: object) -> str:
    reason = "hermetic_replay_protocol_request_decision_time_invalid"
    text = _require_exact_text(value, reason=reason)
    try:
        parsed = datetime.strptime(text, _CLOCK_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        _fail(reason)
    if parsed < _EPOCH:
        _fail(reason)
    canonical = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if canonical != text:
        _fail(reason)
    return text


def _domain_hash(domain_separator: bytes, material: object) -> str:
    return hashlib.sha256(domain_separator + _canonical_json_bytes(material)).hexdigest()


def _normalized_request_material(
    *,
    request_nonce: object,
    run_id: object,
    cycle_id: object,
    decision_id: object,
    manifest_address: object,
    selected_row_address: object,
    symbol: object,
    timeframe: object,
    decision_time: object,
) -> dict[str, object]:
    nonce = _require_pattern(
        request_nonce,
        _NONCE_RE,
        reason="hermetic_replay_protocol_request_nonce_invalid",
    )
    normalized_symbol = _require_pattern(
        symbol,
        _SYMBOL_RE,
        reason="hermetic_replay_protocol_request_symbol_invalid",
    )
    normalized_timeframe = _require_exact_text(
        timeframe,
        reason="hermetic_replay_protocol_request_timeframe_invalid",
    )
    if normalized_timeframe not in SUPPORTED_HERMETIC_REPLAY_TIMEFRAMES_V4:
        _fail("hermetic_replay_protocol_request_timeframe_invalid")
    return {
        "schema_version": CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_SCHEMA_VERSION,
        "contract_version": CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_CONTRACT_VERSION,
        "request_nonce": nonce,
        "run_id": _require_identifier(
            run_id,
            reason="hermetic_replay_protocol_request_run_id_invalid",
        ),
        "cycle_id": _require_identifier(
            cycle_id,
            reason="hermetic_replay_protocol_request_cycle_id_invalid",
        ),
        "decision_id": _require_identifier(
            decision_id,
            reason="hermetic_replay_protocol_request_decision_id_invalid",
        ),
        "manifest_address": _normalize_address(
            manifest_address,
            maximum_byte_count=MAX_HERMETIC_REPLAY_MANIFEST_BYTES_V4,
            reason="hermetic_replay_protocol_request_manifest_address_invalid",
        ),
        "selected_row_address": _normalize_address(
            selected_row_address,
            maximum_byte_count=MAX_HERMETIC_REPLAY_SELECTED_ROW_BYTES_V4,
            reason="hermetic_replay_protocol_request_selected_row_address_invalid",
        ),
        "symbol": normalized_symbol,
        "timeframe": normalized_timeframe,
        "decision_time": _require_decision_time(decision_time),
    }


def encode_canonical_ohlcv_hermetic_replay_request_v4(
    *,
    request_nonce: object,
    run_id: object,
    cycle_id: object,
    decision_id: object,
    manifest_address: object,
    selected_row_address: object,
    symbol: object,
    timeframe: object,
    decision_time: object,
) -> bytes:
    """Encode one exact audit-only replay request as canonical ASCII JSON."""

    material = _normalized_request_material(
        request_nonce=request_nonce,
        run_id=run_id,
        cycle_id=cycle_id,
        decision_id=decision_id,
        manifest_address=manifest_address,
        selected_row_address=selected_row_address,
        symbol=symbol,
        timeframe=timeframe,
        decision_time=decision_time,
    )
    document = dict(material)
    document["request_sha256"] = _domain_hash(
        CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_DOMAIN_SEPARATOR,
        material,
    )
    encoded = _canonical_json_bytes(document)
    if len(encoded) > MAX_HERMETIC_REPLAY_REQUEST_BYTES_V4:
        _fail("hermetic_replay_protocol_request_document_size_invalid")
    return encoded


def validate_canonical_ohlcv_hermetic_replay_request_v4(
    document: object,
) -> MappingProxyType[str, object]:
    """Validate and detach one canonical replay request without granting authority."""

    parsed = _parse_exact_canonical_object(
        document,
        max_document_bytes=MAX_HERMETIC_REPLAY_REQUEST_BYTES_V4,
        max_nodes=MAX_HERMETIC_REPLAY_REQUEST_JSON_NODES_V4,
        max_text_bytes=MAX_HERMETIC_REPLAY_REQUEST_TEXT_BYTES_V4,
        max_string_bytes=MAX_HERMETIC_REPLAY_REQUEST_STRING_BYTES_V4,
        kind="request",
    )
    if FORBIDDEN_HERMETIC_REPLAY_REQUEST_FIELDS_V4.intersection(parsed):
        _fail("hermetic_replay_protocol_request_policy_injection_forbidden")
    request = _require_exact_fields(
        parsed,
        _REQUEST_FIELDS,
        reason="hermetic_replay_protocol_request_fields_invalid",
    )
    if (
        request["schema_version"] != CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_SCHEMA_VERSION
        or request["contract_version"]
        != CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_CONTRACT_VERSION
    ):
        _fail("hermetic_replay_protocol_request_version_invalid")
    material = _normalized_request_material(
        request_nonce=request["request_nonce"],
        run_id=request["run_id"],
        cycle_id=request["cycle_id"],
        decision_id=request["decision_id"],
        manifest_address=request["manifest_address"],
        selected_row_address=request["selected_row_address"],
        symbol=request["symbol"],
        timeframe=request["timeframe"],
        decision_time=request["decision_time"],
    )
    supplied_digest = _require_sha256(
        request["request_sha256"],
        reason="hermetic_replay_protocol_request_digest_invalid",
    )
    expected_digest = _domain_hash(
        CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_DOMAIN_SEPARATOR,
        material,
    )
    if not hmac.compare_digest(supplied_digest, expected_digest):
        _fail("hermetic_replay_protocol_request_digest_mismatch")
    detached = dict(material)
    detached["manifest_address"] = MappingProxyType(
        dict(cast(dict[str, object], material["manifest_address"]))
    )
    detached["selected_row_address"] = MappingProxyType(
        dict(cast(dict[str, object], material["selected_row_address"]))
    )
    detached["request_sha256"] = expected_digest
    return MappingProxyType(detached)


def _require_policy_token(value: object, *, version: bool, reason: str) -> str:
    return _require_pattern(value, _VERSION_RE if version else _POLICY_TOKEN_RE, reason=reason)


def _normalize_policy_document_base64(value: object) -> tuple[str, bytes]:
    reason = "hermetic_replay_protocol_policy_channel_policy_document_invalid"
    text = _require_exact_text(
        value,
        reason=reason,
        maximum_bytes=MAX_HERMETIC_REPLAY_POLICY_BASE64_BYTES_V4,
    )
    if not 1 <= len(text) <= MAX_HERMETIC_REPLAY_POLICY_BASE64_BYTES_V4:
        _fail(reason)
    try:
        decoded = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        _fail(reason)
    if (
        not 1 <= len(decoded) <= MAX_HERMETIC_REPLAY_POLICY_DOCUMENT_BYTES_V4
        or base64.b64encode(decoded).decode("ascii") != text
    ):
        _fail(reason)
    return text, bytes(decoded)


def _normalized_policy_channel_material(
    *,
    expected_policy_sha256: object,
    expected_registry_id: object,
    expected_registry_version: object,
    expected_policy_id: object,
    expected_policy_revision: object,
    policy_document_base64: object,
) -> tuple[dict[str, object], bytes]:
    if (
        type(expected_policy_revision) is not int
        or not 1 <= expected_policy_revision <= _MAX_SIGNED_64
    ):
        _fail("hermetic_replay_protocol_policy_channel_policy_revision_invalid")
    normalized_base64, policy_document = _normalize_policy_document_base64(policy_document_base64)
    material: dict[str, object] = {
        "schema_version": CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_CHANNEL_V4_SCHEMA_VERSION,
        "contract_version": CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_CONTRACT_VERSION,
        "expected_policy_sha256": _require_sha256(
            expected_policy_sha256,
            reason="hermetic_replay_protocol_policy_channel_policy_digest_invalid",
        ),
        "expected_registry_id": _require_policy_token(
            expected_registry_id,
            version=False,
            reason="hermetic_replay_protocol_policy_channel_registry_id_invalid",
        ),
        "expected_registry_version": _require_policy_token(
            expected_registry_version,
            version=True,
            reason="hermetic_replay_protocol_policy_channel_registry_version_invalid",
        ),
        "expected_policy_id": _require_policy_token(
            expected_policy_id,
            version=False,
            reason="hermetic_replay_protocol_policy_channel_policy_id_invalid",
        ),
        "expected_policy_revision": expected_policy_revision,
        "policy_document_base64": normalized_base64,
    }
    return material, policy_document


def encode_canonical_ohlcv_hermetic_replay_policy_channel_v4(
    *,
    expected_policy_sha256: object,
    expected_registry_id: object,
    expected_registry_version: object,
    expected_policy_id: object,
    expected_policy_revision: object,
    policy_document: object,
) -> bytes:
    """Encode exact policy bytes in a separate canonical audit-only frame."""

    if type(policy_document) is not bytes:
        _fail("hermetic_replay_protocol_policy_channel_policy_document_exact_bytes_required")
    if not 1 <= len(policy_document) <= MAX_HERMETIC_REPLAY_POLICY_DOCUMENT_BYTES_V4:
        _fail("hermetic_replay_protocol_policy_channel_policy_document_size_invalid")
    policy_base64 = base64.b64encode(policy_document).decode("ascii")
    material, detached_document = _normalized_policy_channel_material(
        expected_policy_sha256=expected_policy_sha256,
        expected_registry_id=expected_registry_id,
        expected_registry_version=expected_registry_version,
        expected_policy_id=expected_policy_id,
        expected_policy_revision=expected_policy_revision,
        policy_document_base64=policy_base64,
    )
    if detached_document != policy_document:
        _fail("hermetic_replay_protocol_policy_channel_policy_document_invalid")
    frame = dict(material)
    frame["policy_channel_sha256"] = _domain_hash(
        CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_CHANNEL_V4_DOMAIN_SEPARATOR,
        material,
    )
    encoded = _canonical_json_bytes(frame)
    if len(encoded) > MAX_HERMETIC_REPLAY_POLICY_CHANNEL_BYTES_V4:
        _fail("hermetic_replay_protocol_policy_channel_document_size_invalid")
    return encoded


def validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(
    document: object,
) -> MappingProxyType[str, object]:
    """Validate a policy frame without claiming channel sealing or provenance."""

    parsed = _parse_exact_canonical_object(
        document,
        max_document_bytes=MAX_HERMETIC_REPLAY_POLICY_CHANNEL_BYTES_V4,
        max_nodes=MAX_HERMETIC_REPLAY_POLICY_CHANNEL_JSON_NODES_V4,
        max_text_bytes=MAX_HERMETIC_REPLAY_POLICY_CHANNEL_TEXT_BYTES_V4,
        max_string_bytes=MAX_HERMETIC_REPLAY_POLICY_BASE64_BYTES_V4,
        kind="policy_channel",
    )
    channel = _require_exact_fields(
        parsed,
        _POLICY_CHANNEL_FIELDS,
        reason="hermetic_replay_protocol_policy_channel_fields_invalid",
    )
    if (
        channel["schema_version"]
        != CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_CHANNEL_V4_SCHEMA_VERSION
        or channel["contract_version"]
        != CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_CONTRACT_VERSION
    ):
        _fail("hermetic_replay_protocol_policy_channel_version_invalid")
    material, policy_document = _normalized_policy_channel_material(
        expected_policy_sha256=channel["expected_policy_sha256"],
        expected_registry_id=channel["expected_registry_id"],
        expected_registry_version=channel["expected_registry_version"],
        expected_policy_id=channel["expected_policy_id"],
        expected_policy_revision=channel["expected_policy_revision"],
        policy_document_base64=channel["policy_document_base64"],
    )
    supplied_digest = _require_sha256(
        channel["policy_channel_sha256"],
        reason="hermetic_replay_protocol_policy_channel_digest_invalid",
    )
    expected_digest = _domain_hash(
        CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_CHANNEL_V4_DOMAIN_SEPARATOR,
        material,
    )
    if not hmac.compare_digest(supplied_digest, expected_digest):
        _fail("hermetic_replay_protocol_policy_channel_digest_mismatch")
    detached = dict(material)
    detached["policy_channel_sha256"] = expected_digest
    detached["policy_document"] = policy_document
    detached["policy_channel_sealing_verified"] = False
    detached["policy_channel_immutability_verified"] = False
    detached["policy_source_authenticated"] = False
    detached["audit_only"] = True
    return MappingProxyType(detached)


__all__ = [
    "CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_CHANNEL_V4_DOMAIN_SEPARATOR",
    "CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_CHANNEL_V4_SCHEMA_VERSION",
    "CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_CONTRACT_VERSION",
    "CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_DOMAIN_SEPARATOR",
    "CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_SCHEMA_VERSION",
    "CanonicalOhlcvHermeticReplayProtocolV4Error",
    "FORBIDDEN_HERMETIC_REPLAY_REQUEST_FIELDS_V4",
    "MAX_HERMETIC_REPLAY_MANIFEST_BYTES_V4",
    "MAX_HERMETIC_REPLAY_POLICY_BASE64_BYTES_V4",
    "MAX_HERMETIC_REPLAY_POLICY_CHANNEL_BYTES_V4",
    "MAX_HERMETIC_REPLAY_POLICY_DOCUMENT_BYTES_V4",
    "MAX_HERMETIC_REPLAY_REQUEST_BYTES_V4",
    "MAX_HERMETIC_REPLAY_SELECTED_ROW_BYTES_V4",
    "SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION_V4",
    "SUPPORTED_HERMETIC_REPLAY_TIMEFRAMES_V4",
    "encode_canonical_ohlcv_hermetic_replay_policy_channel_v4",
    "encode_canonical_ohlcv_hermetic_replay_request_v4",
    "validate_canonical_ohlcv_hermetic_replay_policy_channel_v4",
    "validate_canonical_ohlcv_hermetic_replay_request_v4",
]
