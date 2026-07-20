from __future__ import annotations

import ast
import base64
import copy
import hashlib
import inspect
import json
import sys
from types import MappingProxyType
from typing import Any, cast

import pytest

from v2.backend.app.services.native_trainer import (
    canonical_ohlcv_hermetic_replay_protocol_v4 as protocol_module,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_hermetic_replay_protocol_v4 import (
    CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_CHANNEL_V4_DOMAIN_SEPARATOR,
    CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_CHANNEL_V4_SCHEMA_VERSION,
    CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_CONTRACT_VERSION,
    CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_DOMAIN_SEPARATOR,
    CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_SCHEMA_VERSION,
    FORBIDDEN_HERMETIC_REPLAY_REQUEST_FIELDS_V4,
    MAX_HERMETIC_REPLAY_MANIFEST_BYTES_V4,
    MAX_HERMETIC_REPLAY_POLICY_CHANNEL_BYTES_V4,
    MAX_HERMETIC_REPLAY_POLICY_DOCUMENT_BYTES_V4,
    MAX_HERMETIC_REPLAY_REQUEST_BYTES_V4,
    MAX_HERMETIC_REPLAY_SELECTED_ROW_BYTES_V4,
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION_V4,
    CanonicalOhlcvHermeticReplayProtocolV4Error,
    encode_canonical_ohlcv_hermetic_replay_policy_channel_v4,
    encode_canonical_ohlcv_hermetic_replay_request_v4,
    validate_canonical_ohlcv_hermetic_replay_policy_channel_v4,
    validate_canonical_ohlcv_hermetic_replay_request_v4,
)

_MANIFEST_DIGEST = hashlib.sha256(b"manifest-v4").hexdigest()
_SELECTED_ROW_DIGEST = hashlib.sha256(b"selected-row-v4").hexdigest()
_ALTERNATE_MANIFEST_DIGEST = hashlib.sha256(b"alternate-manifest-v4").hexdigest()
_ALTERNATE_ROW_DIGEST = hashlib.sha256(b"alternate-row-v4").hexdigest()
_NONCE = "0123456789abcdef" * 4
_ALTERNATE_NONCE = "fedcba9876543210" * 4
_POLICY_DOCUMENT = b'{"audit_only":true,"schema_version":"fixture_policy_v4"}'
_EXPECTED_POLICY_SHA256 = hashlib.sha256(b"expected-policy-v4").hexdigest()


class _BytesSubclass(bytes):
    pass


class _StringSubclass(str):
    pass


class _IntSubclass(int):
    pass


class _DictSubclass(dict[str, object]):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _decoded_object(document: bytes) -> dict[str, object]:
    parsed = json.loads(document)
    assert type(parsed) is dict
    return cast(dict[str, object], parsed)


def _address(digest: str, byte_count: int) -> dict[str, object]:
    return {
        "schema_version": SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION_V4,
        "payload_sha256": digest,
        "payload_byte_count": byte_count,
        "relative_path": f"sha256/{digest[:2]}/{digest}",
    }


def _request_values() -> dict[str, object]:
    return {
        "request_nonce": _NONCE,
        "run_id": "trainer_run_20260720_001",
        "cycle_id": "feature_cycle_20260720_001",
        "decision_id": "decision_BTCUSDT_1m_001",
        "manifest_address": _address(_MANIFEST_DIGEST, 8192),
        "selected_row_address": _address(_SELECTED_ROW_DIGEST, 512),
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-07-20T12:34:56.123000Z",
    }


def _encode_request(values: dict[str, object]) -> bytes:
    return encode_canonical_ohlcv_hermetic_replay_request_v4(
        request_nonce=values["request_nonce"],
        run_id=values["run_id"],
        cycle_id=values["cycle_id"],
        decision_id=values["decision_id"],
        manifest_address=values["manifest_address"],
        selected_row_address=values["selected_row_address"],
        symbol=values["symbol"],
        timeframe=values["timeframe"],
        decision_time=values["decision_time"],
    )


def _request_material(frame: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in frame.items() if key != "request_sha256"}


def _request_digest(frame: dict[str, object]) -> str:
    return hashlib.sha256(
        CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_DOMAIN_SEPARATOR
        + _canonical(_request_material(frame))
    ).hexdigest()


def _policy_values(policy_document: object = _POLICY_DOCUMENT) -> dict[str, object]:
    return {
        "expected_policy_sha256": _EXPECTED_POLICY_SHA256,
        "expected_registry_id": "native-trainer-hermetic-policy-registry",
        "expected_registry_version": "registry-v4.1",
        "expected_policy_id": "canonical-binance-ohlcv-hermetic-replay",
        "expected_policy_revision": 1,
        "policy_document": policy_document,
    }


def _encode_policy_channel(values: dict[str, object]) -> bytes:
    return encode_canonical_ohlcv_hermetic_replay_policy_channel_v4(
        expected_policy_sha256=values["expected_policy_sha256"],
        expected_registry_id=values["expected_registry_id"],
        expected_registry_version=values["expected_registry_version"],
        expected_policy_id=values["expected_policy_id"],
        expected_policy_revision=values["expected_policy_revision"],
        policy_document=values["policy_document"],
    )


def _policy_channel_material(frame: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in frame.items() if key != "policy_channel_sha256"}


def _policy_channel_digest(frame: dict[str, object]) -> str:
    return hashlib.sha256(
        CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_CHANNEL_V4_DOMAIN_SEPARATOR
        + _canonical(_policy_channel_material(frame))
    ).hexdigest()


def test_request_round_trip_is_exact_canonical_ascii_detached_and_immutable() -> None:
    values = _request_values()
    manifest = cast(dict[str, object], values["manifest_address"])
    selected_row = cast(dict[str, object], values["selected_row_address"])

    document = _encode_request(values)
    frame = _decoded_object(document)
    result = validate_canonical_ohlcv_hermetic_replay_request_v4(document)

    assert document == _canonical(frame)
    assert document.decode("ascii").encode("ascii") == document
    assert len(document) <= MAX_HERMETIC_REPLAY_REQUEST_BYTES_V4
    assert frame["schema_version"] == CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_SCHEMA_VERSION
    assert frame["contract_version"] == (
        CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_CONTRACT_VERSION
    )
    assert frame["request_sha256"] == _request_digest(frame)
    assert type(result) is type(MappingProxyType({}))
    assert type(result["manifest_address"]) is type(MappingProxyType({}))
    assert type(result["selected_row_address"]) is type(MappingProxyType({}))
    assert result["request_sha256"] == frame["request_sha256"]
    assert result["run_id"] == values["run_id"]

    manifest["payload_byte_count"] = 1
    selected_row["payload_byte_count"] = 1
    assert (
        cast(MappingProxyType[str, object], result["manifest_address"])["payload_byte_count"]
        == 8192
    )
    assert (
        cast(MappingProxyType[str, object], result["selected_row_address"])["payload_byte_count"]
        == 512
    )
    with pytest.raises(TypeError):
        cast(dict[str, object], result)["run_id"] = "changed"
    with pytest.raises(TypeError):
        cast(dict[str, object], result["manifest_address"])["payload_byte_count"] = 1


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("request_nonce", _ALTERNATE_NONCE),
        ("run_id", "trainer_run_20260720_002"),
        ("cycle_id", "feature_cycle_20260720_002"),
        ("decision_id", "decision_BTCUSDT_1m_002"),
        ("manifest_address", _address(_ALTERNATE_MANIFEST_DIGEST, 8192)),
        ("selected_row_address", _address(_ALTERNATE_ROW_DIGEST, 512)),
        ("symbol", "ETHUSDT"),
        ("timeframe", "5m"),
        ("decision_time", "2026-07-20T12:35:56.123000Z"),
    ],
)
def test_request_digest_binds_every_caller_material_field(
    field: str,
    replacement: object,
) -> None:
    frame = _decoded_object(_encode_request(_request_values()))
    original_digest = frame["request_sha256"]
    frame[field] = replacement

    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="request_digest_mismatch",
    ):
        validate_canonical_ohlcv_hermetic_replay_request_v4(_canonical(frame))

    frame["request_sha256"] = _request_digest(frame)
    rebound = validate_canonical_ohlcv_hermetic_replay_request_v4(_canonical(frame))
    assert rebound["request_sha256"] != original_digest


def test_request_hash_is_domain_separated_and_covers_fixed_versions() -> None:
    frame = _decoded_object(_encode_request(_request_values()))
    material = _request_material(frame)
    canonical_material = _canonical(material)

    assert (
        frame["request_sha256"]
        == hashlib.sha256(
            CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_DOMAIN_SEPARATOR + canonical_material
        ).hexdigest()
    )
    assert frame["request_sha256"] != hashlib.sha256(canonical_material).hexdigest()

    material["schema_version"] = "different_schema"
    assert _request_digest({**material, "request_sha256": "0" * 64}) != frame["request_sha256"]


@pytest.mark.parametrize("field", sorted(FORBIDDEN_HERMETIC_REPLAY_REQUEST_FIELDS_V4))
def test_every_policy_root_code_resource_and_authority_injection_is_explicitly_rejected(
    field: str,
) -> None:
    frame = _decoded_object(_encode_request(_request_values()))
    frame[field] = False

    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="request_policy_injection_forbidden",
    ):
        validate_canonical_ohlcv_hermetic_replay_request_v4(_canonical(frame))


def test_unknown_non_policy_request_field_is_rejected_by_exact_field_set() -> None:
    frame = _decoded_object(_encode_request(_request_values()))
    frame["unexpected"] = "value"
    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="request_fields_invalid",
    ):
        validate_canonical_ohlcv_hermetic_replay_request_v4(_canonical(frame))


@pytest.mark.parametrize(
    "document",
    [
        "{}",
        bytearray(b"{}"),
        memoryview(b"{}"),
        _BytesSubclass(b"{}"),
    ],
)
def test_request_validator_requires_exact_builtin_bytes(document: object) -> None:
    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="request_exact_bytes_required",
    ):
        validate_canonical_ohlcv_hermetic_replay_request_v4(document)


@pytest.mark.parametrize(
    ("document", "reason"),
    [
        (b'{"x":1,"x":2}', "duplicate_json_key"),
        (b'{"x":1.0}', "json_float_forbidden"),
        (b'{"x":NaN}', "json_constant_forbidden"),
        (b'{"x":Infinity}', "json_constant_forbidden"),
        (b'{"x":-Infinity}', "json_constant_forbidden"),
        (b'{"x":"\xff"}', "request_json_invalid"),
        (b'{"x":"\\u00e9"}', "non_ascii_text_forbidden"),
        (b"[]", "request_object_required"),
        (b"{}\n", "request_noncanonical_json"),
        (b'{"x":9223372036854775808}', "json_integer_out_of_range"),
    ],
)
def test_request_parser_totalizes_malformed_or_forbidden_json(
    document: bytes,
    reason: str,
) -> None:
    with pytest.raises(CanonicalOhlcvHermeticReplayProtocolV4Error, match=reason):
        validate_canonical_ohlcv_hermetic_replay_request_v4(document)


def test_request_parser_preflights_depth_nodes_and_document_size() -> None:
    deep = b"[" * 9 + b"0" + b"]" * 9
    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="json_depth_limit_exceeded",
    ):
        validate_canonical_ohlcv_hermetic_replay_request_v4(deep)

    node_heavy: dict[str, object] = {f"k{index:02d}": [index] for index in range(32)}
    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="json_node_limit_exceeded",
    ):
        validate_canonical_ohlcv_hermetic_replay_request_v4(_canonical(node_heavy))

    oversized = b"{" + b" " * MAX_HERMETIC_REPLAY_REQUEST_BYTES_V4 + b"}"
    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="request_document_size_invalid",
    ):
        validate_canonical_ohlcv_hermetic_replay_request_v4(oversized)


def test_request_rejects_noncanonical_spacing_key_order_and_trailing_data() -> None:
    frame = _decoded_object(_encode_request(_request_values()))
    noncanonical = json.dumps(frame, sort_keys=False).encode("ascii")
    assert noncanonical != _canonical(frame)
    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="request_noncanonical_json",
    ):
        validate_canonical_ohlcv_hermetic_replay_request_v4(noncanonical)

    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="request_json_invalid",
    ):
        validate_canonical_ohlcv_hermetic_replay_request_v4(
            _encode_request(_request_values()) + b"{}"
        )


@pytest.mark.parametrize(
    ("field", "replacement", "reason"),
    [
        ("request_nonce", "A" * 64, "request_nonce_invalid"),
        ("request_nonce", "0" * 63, "request_nonce_invalid"),
        ("request_nonce", _StringSubclass(_NONCE), "request_nonce_invalid"),
        ("run_id", "contains/slash", "request_run_id_invalid"),
        ("run_id", "x" * 129, "request_run_id_invalid"),
        ("cycle_id", True, "request_cycle_id_invalid"),
        ("decision_id", _StringSubclass("decision"), "request_decision_id_invalid"),
        ("symbol", "btcUSDT", "request_symbol_invalid"),
        ("symbol", "ÄBCUSDT", "request_symbol_invalid"),
        ("timeframe", "2m", "request_timeframe_invalid"),
        ("decision_time", "2026-07-20T12:34:56.123Z", "request_decision_time_invalid"),
        ("decision_time", "2026-07-20T12:34:56.123000+00:00", "request_decision_time_invalid"),
        ("decision_time", "1969-12-31T23:59:59.999999Z", "request_decision_time_invalid"),
    ],
)
def test_request_encoder_rejects_invalid_exact_scalar_contracts(
    field: str,
    replacement: object,
    reason: str,
) -> None:
    values = _request_values()
    values[field] = replacement
    with pytest.raises(CanonicalOhlcvHermeticReplayProtocolV4Error, match=reason):
        _encode_request(values)


def test_request_encoder_preflights_caller_text_before_transport_allocation() -> None:
    values = _request_values()
    values["decision_time"] = "x" * (MAX_HERMETIC_REPLAY_REQUEST_BYTES_V4 + 1)
    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="request_decision_time_invalid",
    ):
        _encode_request(values)


@pytest.mark.parametrize("address_name", ["manifest_address", "selected_row_address"])
@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        ("schema_version", "wrong_schema"),
        ("payload_sha256", "A" * 64),
        ("payload_byte_count", True),
        ("payload_byte_count", 0),
        ("relative_path", "sha256/wrong/path"),
    ],
)
def test_request_encoder_rejects_malformed_address_fields(
    address_name: str,
    mutation: str,
    value: object,
) -> None:
    values = _request_values()
    address = cast(dict[str, object], values[address_name])
    address[mutation] = value
    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match=f"request_{address_name}_invalid",
    ):
        _encode_request(values)


@pytest.mark.parametrize("address_name", ["manifest_address", "selected_row_address"])
def test_request_encoder_requires_exact_address_dict_and_field_set(address_name: str) -> None:
    values = _request_values()
    values[address_name] = _DictSubclass(cast(dict[str, object], values[address_name]))
    with pytest.raises(CanonicalOhlcvHermeticReplayProtocolV4Error, match="address_invalid"):
        _encode_request(values)

    values = _request_values()
    address = cast(dict[str, object], values[address_name])
    address["extra"] = "forbidden"
    with pytest.raises(CanonicalOhlcvHermeticReplayProtocolV4Error, match="address_invalid"):
        _encode_request(values)


def test_request_address_resource_ceilings_are_role_specific() -> None:
    values = _request_values()
    manifest = cast(dict[str, object], values["manifest_address"])
    manifest["payload_byte_count"] = MAX_HERMETIC_REPLAY_MANIFEST_BYTES_V4
    selected = cast(dict[str, object], values["selected_row_address"])
    selected["payload_byte_count"] = MAX_HERMETIC_REPLAY_SELECTED_ROW_BYTES_V4
    validate_canonical_ohlcv_hermetic_replay_request_v4(_encode_request(values))

    manifest["payload_byte_count"] = MAX_HERMETIC_REPLAY_MANIFEST_BYTES_V4 + 1
    with pytest.raises(CanonicalOhlcvHermeticReplayProtocolV4Error, match="manifest_address"):
        _encode_request(values)

    values = _request_values()
    selected = cast(dict[str, object], values["selected_row_address"])
    selected["payload_byte_count"] = MAX_HERMETIC_REPLAY_SELECTED_ROW_BYTES_V4 + 1
    with pytest.raises(CanonicalOhlcvHermeticReplayProtocolV4Error, match="selected_row_address"):
        _encode_request(values)


def test_request_encoder_rejects_exact_primitive_subclasses_without_invoking_hooks() -> None:
    values = _request_values()
    manifest = cast(dict[str, object], values["manifest_address"])
    manifest[_StringSubclass("unexpected")] = "value"
    with pytest.raises(CanonicalOhlcvHermeticReplayProtocolV4Error, match="manifest_address"):
        _encode_request(values)

    values = _request_values()
    selected = cast(dict[str, object], values["selected_row_address"])
    selected["payload_byte_count"] = _IntSubclass(512)
    with pytest.raises(CanonicalOhlcvHermeticReplayProtocolV4Error, match="selected_row_address"):
        _encode_request(values)


def test_request_address_is_detached_before_any_later_caller_mutation() -> None:
    values = _request_values()
    original = copy.deepcopy(cast(dict[str, object], values["manifest_address"]))
    alternate = _address(_ALTERNATE_MANIFEST_DIGEST, 16384)
    address = cast(dict[str, object], values["manifest_address"])
    snapshot_taken = False
    target_code = protocol_module._require_exact_fields.__code__

    def mutate_after_snapshot(
        frame: object,
        event: str,
        _argument: object,
    ) -> Any:
        nonlocal snapshot_taken
        frame_locals = getattr(frame, "f_locals", {})
        frame_code = getattr(frame, "f_code", None)
        if (
            not snapshot_taken
            and frame_code is target_code
            and event == "line"
            and type(frame_locals) is dict
            and "items" in frame_locals
        ):
            address.clear()
            address.update(alternate)
            snapshot_taken = True
        return mutate_after_snapshot

    sys.settrace(mutate_after_snapshot)
    try:
        document = _encode_request(values)
    finally:
        sys.settrace(None)

    assert snapshot_taken is True
    assert address == alternate
    frame = _decoded_object(document)
    assert frame["manifest_address"] == original
    validated = validate_canonical_ohlcv_hermetic_replay_request_v4(document)
    assert dict(cast(MappingProxyType[str, object], validated["manifest_address"])) == original


def test_policy_channel_round_trip_preserves_exact_bytes_without_sealing_or_auth_claim() -> None:
    document = _encode_policy_channel(_policy_values())
    frame = _decoded_object(document)
    result = validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(document)

    assert document == _canonical(frame)
    assert document.decode("ascii").encode("ascii") == document
    assert frame["schema_version"] == (
        CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_CHANNEL_V4_SCHEMA_VERSION
    )
    assert frame["contract_version"] == (
        CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_CONTRACT_VERSION
    )
    assert frame["policy_channel_sha256"] == _policy_channel_digest(frame)
    assert result["policy_document"] == _POLICY_DOCUMENT
    assert result["policy_channel_sealing_verified"] is False
    assert result["policy_channel_immutability_verified"] is False
    assert result["policy_source_authenticated"] is False
    assert result["audit_only"] is True
    assert type(result) is type(MappingProxyType({}))
    with pytest.raises(TypeError):
        cast(dict[str, object], result)["policy_source_authenticated"] = True


@pytest.mark.parametrize(
    "policy_document",
    [
        b"\x00\xff\x80exact bytes\n",
        b" { not canonical policy JSON } \n",
        bytes(range(256)),
    ],
)
def test_policy_channel_base64_preserves_arbitrary_exact_policy_bytes(
    policy_document: bytes,
) -> None:
    result = validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(
        _encode_policy_channel(_policy_values(policy_document))
    )
    assert result["policy_document"] == policy_document
    assert base64.b64decode(cast(str, result["policy_document_base64"]), validate=True) == (
        policy_document
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("expected_policy_sha256", hashlib.sha256(b"alternate-policy").hexdigest()),
        ("expected_registry_id", "alternate-registry"),
        ("expected_registry_version", "registry-v4.2"),
        ("expected_policy_id", "alternate-policy-id"),
        ("expected_policy_revision", 2),
        ("policy_document_base64", base64.b64encode(b'{"alternate":true}').decode("ascii")),
    ],
)
def test_policy_channel_digest_binds_every_material_field(
    field: str,
    replacement: object,
) -> None:
    frame = _decoded_object(_encode_policy_channel(_policy_values()))
    original_digest = frame["policy_channel_sha256"]
    frame[field] = replacement

    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="policy_channel_digest_mismatch",
    ):
        validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(_canonical(frame))

    frame["policy_channel_sha256"] = _policy_channel_digest(frame)
    rebound = validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(_canonical(frame))
    assert rebound["policy_channel_sha256"] != original_digest


def test_policy_channel_hash_is_domain_separated_and_not_policy_authentication() -> None:
    values = _policy_values()
    values["expected_policy_sha256"] = "0" * 64
    document = _encode_policy_channel(values)
    frame = _decoded_object(document)
    material = _policy_channel_material(frame)
    canonical_material = _canonical(material)
    result = validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(document)

    assert (
        frame["policy_channel_sha256"]
        == hashlib.sha256(
            CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_CHANNEL_V4_DOMAIN_SEPARATOR + canonical_material
        ).hexdigest()
    )
    assert frame["policy_channel_sha256"] != hashlib.sha256(canonical_material).hexdigest()
    assert result["expected_policy_sha256"] == "0" * 64
    assert result["policy_source_authenticated"] is False


@pytest.mark.parametrize(
    ("field", "replacement", "reason"),
    [
        ("expected_policy_sha256", "A" * 64, "policy_digest_invalid"),
        ("expected_policy_sha256", _StringSubclass("0" * 64), "policy_digest_invalid"),
        ("expected_registry_id", "has space", "registry_id_invalid"),
        ("expected_registry_version", "has/slash", "registry_version_invalid"),
        ("expected_policy_id", True, "policy_id_invalid"),
        ("expected_policy_revision", True, "policy_revision_invalid"),
        ("expected_policy_revision", 0, "policy_revision_invalid"),
        ("expected_policy_revision", _IntSubclass(1), "policy_revision_invalid"),
    ],
)
def test_policy_channel_encoder_rejects_invalid_exact_verifier_coordinates(
    field: str,
    replacement: object,
    reason: str,
) -> None:
    values = _policy_values()
    values[field] = replacement
    with pytest.raises(CanonicalOhlcvHermeticReplayProtocolV4Error, match=reason):
        _encode_policy_channel(values)


@pytest.mark.parametrize(
    "policy_document",
    [
        "{}",
        bytearray(b"{}"),
        memoryview(b"{}"),
        _BytesSubclass(b"{}"),
    ],
)
def test_policy_channel_encoder_requires_exact_builtin_policy_bytes(
    policy_document: object,
) -> None:
    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="policy_document_exact_bytes_required",
    ):
        _encode_policy_channel(_policy_values(policy_document))


def test_policy_channel_policy_document_resource_boundary_is_exact() -> None:
    maximum = b"x" * MAX_HERMETIC_REPLAY_POLICY_DOCUMENT_BYTES_V4
    encoded = _encode_policy_channel(_policy_values(maximum))
    assert len(encoded) <= MAX_HERMETIC_REPLAY_POLICY_CHANNEL_BYTES_V4
    result = validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(encoded)
    assert result["policy_document"] == maximum

    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="policy_document_size_invalid",
    ):
        _encode_policy_channel(
            _policy_values(b"x" * (MAX_HERMETIC_REPLAY_POLICY_DOCUMENT_BYTES_V4 + 1))
        )

    oversized_frame = b"{" + b" " * MAX_HERMETIC_REPLAY_POLICY_CHANNEL_BYTES_V4 + b"}"
    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="policy_channel_document_size_invalid",
    ):
        validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(oversized_frame)


@pytest.mark.parametrize(
    "invalid_base64",
    [
        "",
        "YQ=",
        "YQ===",
        "Y Q==",
        "YQ==\n",
        "____",
        "*A==",
    ],
)
def test_policy_channel_rejects_noncanonical_or_invalid_base64(invalid_base64: str) -> None:
    frame = _decoded_object(_encode_policy_channel(_policy_values()))
    frame["policy_document_base64"] = invalid_base64
    frame["policy_channel_sha256"] = _policy_channel_digest(frame)
    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="policy_document_invalid",
    ):
        validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(_canonical(frame))


@pytest.mark.parametrize(
    "document",
    ["{}", bytearray(b"{}"), memoryview(b"{}"), _BytesSubclass(b"{}")],
)
def test_policy_channel_validator_requires_exact_builtin_bytes(document: object) -> None:
    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="policy_channel_exact_bytes_required",
    ):
        validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(document)


def test_policy_channel_rejects_unknown_fields_wrong_versions_and_trailing_bytes() -> None:
    frame = _decoded_object(_encode_policy_channel(_policy_values()))
    extra = copy.deepcopy(frame)
    extra["policy_channel_sealed"] = True
    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="policy_channel_fields_invalid",
    ):
        validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(_canonical(extra))

    wrong_version = copy.deepcopy(frame)
    wrong_version["schema_version"] = "wrong"
    wrong_version["policy_channel_sha256"] = _policy_channel_digest(wrong_version)
    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="policy_channel_version_invalid",
    ):
        validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(_canonical(wrong_version))

    with pytest.raises(
        CanonicalOhlcvHermeticReplayProtocolV4Error,
        match="policy_channel_json_invalid",
    ):
        validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(
            _encode_policy_channel(_policy_values()) + b"{}"
        )


def test_policy_channel_parser_totalizes_duplicate_float_nonfinite_and_nonascii() -> None:
    invalid_documents = (
        (b'{"x":1,"x":2}', "duplicate_json_key"),
        (b'{"x":1.0}', "json_float_forbidden"),
        (b'{"x":NaN}', "json_constant_forbidden"),
        (b'{"x":"\\u00e9"}', "non_ascii_text_forbidden"),
    )
    for document, reason in invalid_documents:
        with pytest.raises(CanonicalOhlcvHermeticReplayProtocolV4Error, match=reason):
            validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(document)


def test_protocol_module_is_stdlib_only_and_has_no_runtime_or_mutating_calls() -> None:
    source = inspect.getsource(protocol_module)
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    called_names: set[str] = set()
    called_attributes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called_names.add(node.func.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            called_attributes.add(node.func.attr)

    assert imported_roots <= {
        "__future__",
        "base64",
        "binascii",
        "datetime",
        "hashlib",
        "hmac",
        "json",
        "re",
        "types",
        "typing",
    }
    assert called_names.isdisjoint({"eval", "exec", "open", "compile", "__import__"})
    assert called_attributes.isdisjoint(
        {
            "chmod",
            "chown",
            "connect",
            "mkdir",
            "open",
            "publish",
            "rename",
            "set",
            "spawn",
            "unlink",
            "write",
        }
    )
    assert "redis" not in imported_roots
    assert "subprocess" not in imported_roots


def test_protocol_exports_no_encode_or_validate_result_authority_true() -> None:
    request = validate_canonical_ohlcv_hermetic_replay_request_v4(
        _encode_request(_request_values())
    )
    channel = validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(
        _encode_policy_channel(_policy_values())
    )
    assert not any(value is True for value in request.values())
    true_channel_fields = {key for key, value in channel.items() if value is True}
    assert true_channel_fields == {"audit_only"}
    assert channel["policy_channel_sealing_verified"] is False
    assert channel["policy_channel_immutability_verified"] is False
    assert channel["policy_source_authenticated"] is False
