from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.services.native_trainer.profiled_training_external_witness_client_v1 import (
    MAX_PROFILED_WITNESS_WIRE_BYTES,
    PROFILED_WITNESS_COMPARE_APPEND_REQUEST_DOMAIN,
    PROFILED_WITNESS_COMPARE_APPEND_REQUEST_V1_SCHEMA_VERSION,
    PROFILED_WITNESS_PREPARED_APPEND_V1_SCHEMA_VERSION,
    PROFILED_WITNESS_WIRE_APPEND_RECEIPT_V1_SCHEMA_VERSION,
    PROFILED_WITNESS_WIRE_EVENT_SIGNATURE_DOMAIN,
    PROFILED_WITNESS_WIRE_EVENT_V1_SCHEMA_VERSION,
    PROFILED_WITNESS_WIRE_RECEIPT_SIGNATURE_DOMAIN,
    PinnedProfiledTrainingExternalWitnessClientV1,
    ProfiledTrainingExternalWitnessClientV1Error,
    ProfiledTrainingExternalWitnessHttpsTransportV1,
    ProfiledTrainingExternalWitnessPreparedAppendV1,
    ProfiledTrainingExternalWitnessWireResponseV1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_head_v1 import (
    PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
    ProfiledTrainingObservationExternalWitnessV1,
)

WITNESS_ID = "trainer-witness-1"
NAMESPACE = "profiled-trainer"
TOKEN = "test-only-bearer-token-value"  # noqa: S105 - inert test credential
FIXED_VECTOR_PUBLIC_KEY_HEX = (
    "03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8"
)
FIXED_VECTOR_EVENT_BODY = (
    b'{"event_base64":"eA==","event_byte_count":1,'
    b'"event_sha256":"2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881",'
    b'"namespace":"profiled-trainer",'
    b'"previous_event_sha256":"cbb4a45c03b1aca0f8c6f17682ca863b7bf15f20fee904718366c394b93fd374",'
    b'"schema_version":"profiled_training_observation_external_witness_wire_event_v1",'
    b'"sequence":1,"signature_algorithm":"Ed25519",'
    b'"signature_domain":"v2/native-trainer/profiled-observation-external-witness-wire-event/v1",'
    b'"signature_hex":"93abfd3376aed2fde97a9aeeaeb4c1bc173a9dd9382a73e74c08b12e04203897'
    b'30147020d13c124cc821066a24f13657f34b44ed09fde57c07a9f948c5b32b04",'
    b'"signed_at":"2026-07-22T13:00:01.000000Z",'
    b'"witness_id":"trainer-witness-1"}'
)
FIXED_VECTOR_RECEIPT_BODY = (
    b'{"accepted_at":"2026-07-22T13:00:02.000000Z",'
    b'"event_sha256":"2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881",'
    b'"idempotency_key":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
    b'"namespace":"profiled-trainer",'
    b'"previous_event_sha256":"cbb4a45c03b1aca0f8c6f17682ca863b7bf15f20fee904718366c394b93fd374",'
    b'"receipt_payload_base64":"eyJwcm9vZiI6ImZpeGVkIn0=",'
    b'"receipt_payload_byte_count":17,'
    b'"receipt_payload_sha256":"313dcd460f417c121126dc20d9acaf783741fd4c4cb823f6b14dd021d4e7630b",'
    b'"request_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
    b'"schema_version":"profiled_training_observation_external_witness_wire_append_receipt_v1",'
    b'"sequence":1,"signature_algorithm":"Ed25519",'
    b'"signature_domain":"v2/native-trainer/profiled-observation-external-witness-wire-receipt/v1",'
    b'"signature_hex":"0179f727cdb86ddb60f3637f9329aef3423c792126d8f63438dd51afac37f493'
    b'3f930066eb97f3a5bcc6e19582a22db16a79c192a347fb80af0aaf35af25f702",'
    b'"witness_id":"trainer-witness-1"}'
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _raw_public_key(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _signed(
    private_key: Ed25519PrivateKey,
    *,
    domain: str,
    unsigned: dict[str, Any],
) -> bytes:
    signature = private_key.sign(domain.encode("ascii") + b"\0" + _canonical(unsigned))
    return _canonical({**unsigned, "signature_hex": signature.hex()})


class _SignedWitnessTransport:
    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self.private_key = private_key
        self.events: list[tuple[str, bytes, str]] = []
        self.requests: list[tuple[str, str, bytes | None, str | None]] = []
        self.latest_override: tuple[int, str, bytes, str] | None = None
        self.receipt_mutator: Callable[[dict[str, Any]], None] | None = None
        self.readback_mutator: Callable[[dict[str, Any]], None] | None = None
        self.receipts_by_idempotency: dict[
            str,
            tuple[bytes, ProfiledTrainingExternalWitnessWireResponseV1],
        ] = {}
        self.fail_after_append_once = False

    @staticmethod
    def _clock(sequence: int) -> str:
        return f"2026-07-22T13:00:{sequence:02d}.000000Z"

    def _event_body(
        self,
        *,
        sequence: int,
        previous_sha256: str,
        event_bytes: bytes,
        signed_at: str,
        mutate: Callable[[dict[str, Any]], None] | None = None,
    ) -> bytes:
        unsigned = {
            "schema_version": PROFILED_WITNESS_WIRE_EVENT_V1_SCHEMA_VERSION,
            "signature_algorithm": "Ed25519",
            "signature_domain": PROFILED_WITNESS_WIRE_EVENT_SIGNATURE_DOMAIN,
            "witness_id": WITNESS_ID,
            "namespace": NAMESPACE,
            "sequence": sequence,
            "previous_event_sha256": previous_sha256,
            "event_sha256": hashlib.sha256(event_bytes).hexdigest(),
            "event_byte_count": len(event_bytes),
            "event_base64": base64.b64encode(event_bytes).decode("ascii"),
            "signed_at": signed_at,
        }
        if mutate is not None:
            mutate(unsigned)
        return _signed(
            self.private_key,
            domain=PROFILED_WITNESS_WIRE_EVENT_SIGNATURE_DOMAIN,
            unsigned=unsigned,
        )

    def _event_response(
        self,
        sequence: int,
        *,
        mutate: Callable[[dict[str, Any]], None] | None = None,
    ) -> ProfiledTrainingExternalWitnessWireResponseV1:
        previous, event_bytes, signed_at = self.events[sequence - 1]
        return ProfiledTrainingExternalWitnessWireResponseV1(
            status_code=200,
            content_type="application/json",
            body=self._event_body(
                sequence=sequence,
                previous_sha256=previous,
                event_bytes=event_bytes,
                signed_at=signed_at,
                mutate=mutate,
            ),
        )

    def request(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None,
        idempotency_key: str | None,
    ) -> ProfiledTrainingExternalWitnessWireResponseV1:
        self.requests.append((method, path, body, idempotency_key))
        if method == "GET" and path.endswith("/latest"):
            if self.latest_override is not None:
                sequence, previous, event_bytes, signed_at = self.latest_override
                return ProfiledTrainingExternalWitnessWireResponseV1(
                    status_code=200,
                    content_type="application/json",
                    body=self._event_body(
                        sequence=sequence,
                        previous_sha256=previous,
                        event_bytes=event_bytes,
                        signed_at=signed_at,
                    ),
                )
            if not self.events:
                return ProfiledTrainingExternalWitnessWireResponseV1(
                    status_code=404,
                    content_type="",
                    body=b"",
                )
            return self._event_response(len(self.events))
        if method == "GET" and "/events/" in path:
            sequence = int(path.rsplit("/", 1)[1])
            return self._event_response(sequence, mutate=self.readback_mutator)
        if method != "POST" or body is None or idempotency_key is None:
            raise AssertionError("unexpected request")
        prior = self.receipts_by_idempotency.get(idempotency_key)
        if prior is not None:
            prior_body, prior_response = prior
            if prior_body != body:
                return ProfiledTrainingExternalWitnessWireResponseV1(
                    status_code=409,
                    content_type="application/json",
                    body=b"{}",
                )
            return prior_response
        request = json.loads(body)
        expected_sequence = len(self.events)
        expected_previous = (
            PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256
            if not self.events
            else hashlib.sha256(self.events[-1][1]).hexdigest()
        )
        if (
            request["expected_sequence"] != expected_sequence
            or request["expected_event_sha256"] != expected_previous
        ):
            return ProfiledTrainingExternalWitnessWireResponseV1(
                status_code=409,
                content_type="application/json",
                body=b"{}",
            )
        event_bytes = base64.b64decode(request["event_base64"], validate=True)
        sequence = expected_sequence + 1
        accepted_at = self._clock(sequence)
        self.events.append((expected_previous, event_bytes, accepted_at))
        receipt_payload = _canonical(
            {
                "event_sha256": hashlib.sha256(event_bytes).hexdigest(),
                "idempotency_key": idempotency_key,
                "sequence": sequence,
            }
        )
        unsigned = {
            "schema_version": PROFILED_WITNESS_WIRE_APPEND_RECEIPT_V1_SCHEMA_VERSION,
            "signature_algorithm": "Ed25519",
            "signature_domain": PROFILED_WITNESS_WIRE_RECEIPT_SIGNATURE_DOMAIN,
            "witness_id": WITNESS_ID,
            "namespace": NAMESPACE,
            "sequence": sequence,
            "previous_event_sha256": expected_previous,
            "event_sha256": hashlib.sha256(event_bytes).hexdigest(),
            "accepted_at": accepted_at,
            "request_sha256": hashlib.sha256(body).hexdigest(),
            "idempotency_key": idempotency_key,
            "receipt_payload_sha256": hashlib.sha256(receipt_payload).hexdigest(),
            "receipt_payload_byte_count": len(receipt_payload),
            "receipt_payload_base64": base64.b64encode(receipt_payload).decode("ascii"),
        }
        if self.receipt_mutator is not None:
            self.receipt_mutator(unsigned)
        response = ProfiledTrainingExternalWitnessWireResponseV1(
            status_code=201,
            content_type="application/json",
            body=_signed(
                self.private_key,
                domain=PROFILED_WITNESS_WIRE_RECEIPT_SIGNATURE_DOMAIN,
                unsigned=unsigned,
            ),
        )
        self.receipts_by_idempotency[idempotency_key] = (body, response)
        if self.fail_after_append_once:
            self.fail_after_append_once = False
            raise ProfiledTrainingExternalWitnessClientV1Error(
                "PROFILED_WITNESS_HTTP_TRANSPORT_FAILED:ReadTimeout"
            )
        return response


class _StaticTransport:
    def __init__(self, response: ProfiledTrainingExternalWitnessWireResponseV1) -> None:
        self.response = response

    def request(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None,
        idempotency_key: str | None,
    ) -> ProfiledTrainingExternalWitnessWireResponseV1:
        del method, path, body, idempotency_key
        return self.response


class _CloseableStaticTransport(_StaticTransport):
    def __init__(self, response: ProfiledTrainingExternalWitnessWireResponseV1) -> None:
        super().__init__(response)
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _ChunkStream(httpx.SyncByteStream):
    def __init__(self, *chunks: bytes) -> None:
        self.chunks = chunks

    def __iter__(self) -> Iterator[bytes]:
        yield from self.chunks


def _client(
    private_key: Ed25519PrivateKey,
    transport: object,
    *,
    public_key: bytes | None = None,
) -> PinnedProfiledTrainingExternalWitnessClientV1:
    raw = public_key or _raw_public_key(private_key)
    return PinnedProfiledTrainingExternalWitnessClientV1(
        transport=transport,  # type: ignore[arg-type]
        witness_id=WITNESS_ID,
        witness_public_key_bytes=raw,
        expected_witness_public_key_sha256=hashlib.sha256(raw).hexdigest(),
    )


def test_compare_append_reads_back_signed_linear_history() -> None:
    private_key = Ed25519PrivateKey.generate()
    transport = _SignedWitnessTransport(private_key)
    client = _client(private_key, transport)

    assert isinstance(client, ProfiledTrainingObservationExternalWitnessV1)

    first_bytes = b'{"kind":"head","revision":1}'
    first = client.compare_and_append(
        namespace=NAMESPACE,
        expected_sequence=0,
        expected_event_sha256=PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        event_bytes=first_bytes,
    )
    assert first.sequence == 1
    assert first.previous_event_sha256 == PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256
    assert first.event_sha256 == hashlib.sha256(first_bytes).hexdigest()

    second_bytes = b'{"kind":"completion","revision":1}'
    second = client.compare_and_append(
        namespace=NAMESPACE,
        expected_sequence=first.sequence,
        expected_event_sha256=first.event_sha256,
        event_bytes=second_bytes,
    )
    assert second.sequence == 2
    assert second.previous_event_sha256 == first.event_sha256
    assert client.read_event(namespace=NAMESPACE, sequence=2).event_bytes == second_bytes
    latest = client.read_latest(namespace=NAMESPACE)
    assert latest is not None and latest.sequence == 2

    post_bodies = [body for method, _path, body, _key in transport.requests if method == "POST"]
    request = json.loads(post_bodies[0])
    assert request["schema_version"] == PROFILED_WITNESS_COMPARE_APPEND_REQUEST_V1_SCHEMA_VERSION
    assert request["request_domain"] == PROFILED_WITNESS_COMPARE_APPEND_REQUEST_DOMAIN
    assert request["witness_public_key_sha256"] == client.witness_public_key_sha256
    assert request["external_monotonic_manifest_head_verified"] is False
    assert request["full_consumption_external_ack_verified"] is False
    assert request["optimizer_admission_authorized"] is False
    assert request["checkpoint_write_authorized"] is False
    assert request["model_write_authorized"] is False
    assert request["prediction_authorized"] is False
    assert request["paper_trading_authorized"] is False
    assert request["live_execution_authorized"] is False
    assert request["order_submission_authorized"] is False
    assert request["execution_authorized"] is False
    assert request["runtime_wired"] is False


def test_prepare_freezes_exact_request_without_network_and_dispatches_it() -> None:
    private_key = Ed25519PrivateKey.generate()
    transport = _SignedWitnessTransport(private_key)
    client = _client(private_key, transport)

    prepared = client.prepare_compare_and_append(
        namespace=NAMESPACE,
        expected_sequence=0,
        expected_event_sha256=PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        event_bytes=b"durable-before-dispatch",
    )
    repeated = client.prepare_compare_and_append(
        namespace=NAMESPACE,
        expected_sequence=0,
        expected_event_sha256=PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        event_bytes=b"durable-before-dispatch",
    )

    assert type(prepared) is ProfiledTrainingExternalWitnessPreparedAppendV1
    assert prepared == repeated
    assert prepared.schema_version == PROFILED_WITNESS_PREPARED_APPEND_V1_SCHEMA_VERSION
    assert prepared.witness_public_key_sha256 == client.witness_public_key_sha256
    assert prepared.request_sha256 == hashlib.sha256(prepared.request_bytes).hexdigest()
    assert prepared.event_sha256 == hashlib.sha256(prepared.event_bytes).hexdigest()
    assert transport.requests == []
    request = json.loads(prepared.request_bytes)
    assert request["idempotency_key"] == prepared.idempotency_key
    assert request["witness_id"] == prepared.witness_id
    assert request["witness_public_key_sha256"] == prepared.witness_public_key_sha256
    assert request["external_monotonic_manifest_head_verified"] is False
    assert request["full_consumption_external_ack_verified"] is False
    assert request["optimizer_admission_authorized"] is False
    assert request["checkpoint_write_authorized"] is False
    assert request["model_write_authorized"] is False
    assert request["prediction_authorized"] is False
    assert request["paper_trading_authorized"] is False
    assert request["live_execution_authorized"] is False
    assert request["order_submission_authorized"] is False
    assert request["execution_authorized"] is False
    assert request["runtime_wired"] is False

    receipt = client.dispatch_prepared_append(prepared)

    assert receipt.sequence == 1
    post = next(item for item in transport.requests if item[0] == "POST")
    assert post[2] == prepared.request_bytes
    assert post[3] == prepared.idempotency_key


def test_dispatch_reauthenticates_prepared_append_before_network() -> None:
    private_key = Ed25519PrivateKey.generate()
    transport = _SignedWitnessTransport(private_key)
    client = _client(private_key, transport)
    differently_pinned_client = _client(Ed25519PrivateKey.generate(), transport)
    prepared = differently_pinned_client.prepare_compare_and_append(
        namespace=NAMESPACE,
        expected_sequence=0,
        expected_event_sha256=PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        event_bytes=b"prepared",
    )

    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_PREPARED_APPEND_REAUTHENTICATION_FAILED",
    ):
        client.dispatch_prepared_append(prepared)

    assert transport.requests == []


def test_fresh_client_reprepares_exact_persisted_inputs_before_dispatch() -> None:
    private_key = Ed25519PrivateKey.generate()
    transport = _SignedWitnessTransport(private_key)
    first_client = _client(private_key, transport)
    prepared = first_client.prepare_compare_and_append(
        namespace=NAMESPACE,
        expected_sequence=0,
        expected_event_sha256=PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        event_bytes=b"persist-exact-inputs",
    )
    persisted: dict[str, Any] = {
        "namespace": prepared.namespace,
        "witness_id": prepared.witness_id,
        "witness_public_key_sha256": prepared.witness_public_key_sha256,
        "expected_sequence": prepared.expected_sequence,
        "expected_event_sha256": prepared.expected_event_sha256,
        "event_sha256": prepared.event_sha256,
        "event_byte_count": prepared.event_byte_count,
        "event_bytes": bytes(prepared.event_bytes),
        "request_bytes": bytes(prepared.request_bytes),
        "request_sha256": prepared.request_sha256,
        "request_byte_count": prepared.request_byte_count,
        "idempotency_key": prepared.idempotency_key,
    }

    restarted_client = _client(private_key, transport)
    rehydrated = restarted_client.prepare_compare_and_append(
        namespace=persisted["namespace"],
        expected_sequence=persisted["expected_sequence"],
        expected_event_sha256=persisted["expected_event_sha256"],
        event_bytes=persisted["event_bytes"],
    )

    assert rehydrated.request_bytes == persisted["request_bytes"]
    assert rehydrated.witness_id == persisted["witness_id"]
    assert (
        rehydrated.witness_public_key_sha256
        == persisted["witness_public_key_sha256"]
    )
    assert rehydrated.event_sha256 == persisted["event_sha256"]
    assert rehydrated.event_byte_count == persisted["event_byte_count"]
    assert rehydrated.request_sha256 == persisted["request_sha256"]
    assert rehydrated.request_byte_count == persisted["request_byte_count"]
    assert rehydrated.idempotency_key == persisted["idempotency_key"]
    assert transport.requests == []
    assert restarted_client.dispatch_prepared_append(rehydrated).sequence == 1


def test_prepared_append_self_binds_request_fields_before_dispatch() -> None:
    private_key = Ed25519PrivateKey.generate()
    transport = _SignedWitnessTransport(private_key)
    client = _client(private_key, transport)
    prepared = client.prepare_compare_and_append(
        namespace=NAMESPACE,
        expected_sequence=0,
        expected_event_sha256=PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        event_bytes=b"prepared",
    )
    object.__setattr__(prepared, "namespace", "different-namespace")

    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_PREPARED_APPEND_REQUEST_INVALID",
    ):
        prepared.__post_init__()

    assert transport.requests == []


def test_prepare_accepts_largest_safe_predecessor_sequence_without_network() -> None:
    private_key = Ed25519PrivateKey.generate()
    transport = _SignedWitnessTransport(private_key)
    client = _client(private_key, transport)

    prepared = client.prepare_compare_and_append(
        namespace=NAMESPACE,
        expected_sequence=2**63 - 2,
        expected_event_sha256="1" * 64,
        event_bytes=b"upper-safe-sequence",
    )

    assert prepared.expected_sequence == 2**63 - 2
    assert transport.requests == []


@pytest.mark.parametrize("expected_sequence", [True, 2**63 - 1])
def test_prepare_rejects_unsafe_predecessor_sequence_before_network(
    expected_sequence: object,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    transport = _SignedWitnessTransport(private_key)
    client = _client(private_key, transport)

    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_EXPECTED_SEQUENCE_INVALID",
    ):
        client.prepare_compare_and_append(
            namespace=NAMESPACE,
            expected_sequence=expected_sequence,  # type: ignore[arg-type]
            expected_event_sha256="1" * 64,
            event_bytes=b"unsafe-sequence",
        )

    assert transport.requests == []


def test_unsigned_absence_is_never_accepted_as_genesis_proof() -> None:
    private_key = Ed25519PrivateKey.generate()
    client = _client(private_key, _SignedWitnessTransport(private_key))

    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_UNSIGNED_ABSENCE_FORBIDDEN",
    ):
        client.read_latest(namespace=NAMESPACE)


@pytest.mark.parametrize("sequence", [1, 2])
def test_fresh_client_rejects_signed_orphan_chain(sequence: int) -> None:
    private_key = Ed25519PrivateKey.generate()
    transport = _SignedWitnessTransport(private_key)
    if sequence == 2:
        transport.events.append(
            (
                PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
                b"first",
                transport._clock(1),
            )
        )
    transport.latest_override = (
        sequence,
        "f" * 64,
        b"orphan",
        transport._clock(sequence),
    )
    client = _client(private_key, transport)

    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_SIGNED_HEAD_CHAIN_INVALID",
    ):
        client.read_latest(namespace=NAMESPACE)


def test_persisted_signed_head_anchor_rejects_cross_restart_rollback() -> None:
    private_key = Ed25519PrivateKey.generate()
    transport = _SignedWitnessTransport(private_key)
    first_client = _client(private_key, transport)
    first = first_client.compare_and_append(
        namespace=NAMESPACE,
        expected_sequence=0,
        expected_event_sha256=PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        event_bytes=b"first",
    )
    first_client.compare_and_append(
        namespace=NAMESPACE,
        expected_sequence=first.sequence,
        expected_event_sha256=first.event_sha256,
        event_bytes=b"second",
    )
    trusted_envelope = first_client.trusted_head_envelope_bytes(namespace=NAMESPACE)
    raw_public_key = _raw_public_key(private_key)
    restarted_client = PinnedProfiledTrainingExternalWitnessClientV1(
        transport=transport,
        witness_id=WITNESS_ID,
        witness_public_key_bytes=raw_public_key,
        expected_witness_public_key_sha256=hashlib.sha256(raw_public_key).hexdigest(),
        trusted_head_envelope_bytes_by_namespace={NAMESPACE: trusted_envelope},
    )
    transport.latest_override = (
        1,
        PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        b"first",
        transport._clock(1),
    )

    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_SIGNED_HEAD_ROLLBACK",
    ):
        restarted_client.read_latest(namespace=NAMESPACE)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":"x", "signature_hex":"y"}',
        b'{"schema_version":"x","schema_version":"y"}',
        b'{"schema_version":NaN}',
        b'{"schema_version":1.5}',
        b"[]",
        b"\xff",
    ],
)
def test_read_latest_rejects_noncanonical_or_ambiguous_json(raw: bytes) -> None:
    private_key = Ed25519PrivateKey.generate()
    response = ProfiledTrainingExternalWitnessWireResponseV1(
        status_code=200,
        content_type="application/json",
        body=raw,
    )
    client = _client(private_key, _StaticTransport(response))

    with pytest.raises(ProfiledTrainingExternalWitnessClientV1Error):
        client.read_latest(namespace=NAMESPACE)


def test_read_latest_rejects_wrong_signature_key() -> None:
    signer = Ed25519PrivateKey.generate()
    transport = _SignedWitnessTransport(signer)
    transport.events.append(
        (PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256, b"event", transport._clock(1))
    )
    different_key = Ed25519PrivateKey.generate()
    client = _client(different_key, transport)

    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_EVENT_SIGNATURE_UNVERIFIED",
    ):
        client.read_latest(namespace=NAMESPACE)


def test_independent_fixed_ed25519_event_vector_is_accepted() -> None:
    public_key = bytes.fromhex(FIXED_VECTOR_PUBLIC_KEY_HEX)
    response = ProfiledTrainingExternalWitnessWireResponseV1(
        status_code=200,
        content_type="application/json",
        body=FIXED_VECTOR_EVENT_BODY,
    )
    client = PinnedProfiledTrainingExternalWitnessClientV1(
        transport=_StaticTransport(response),
        witness_id=WITNESS_ID,
        witness_public_key_bytes=public_key,
        expected_witness_public_key_sha256=hashlib.sha256(public_key).hexdigest(),
    )

    event = client.read_latest(namespace=NAMESPACE)

    assert event is not None
    assert event.sequence == 1
    assert event.event_bytes == b"x"


def test_independent_fixed_ed25519_receipt_vector_is_accepted() -> None:
    public_key = bytes.fromhex(FIXED_VECTOR_PUBLIC_KEY_HEX)
    client = PinnedProfiledTrainingExternalWitnessClientV1(
        transport=_StaticTransport(
            ProfiledTrainingExternalWitnessWireResponseV1(
                status_code=404,
                content_type="",
                body=b"",
            )
        ),
        witness_id=WITNESS_ID,
        witness_public_key_bytes=public_key,
        expected_witness_public_key_sha256=hashlib.sha256(public_key).hexdigest(),
    )

    receipt = client.verify_append_receipt_envelope(
        signed_receipt_envelope_bytes=FIXED_VECTOR_RECEIPT_BODY,
        expected_namespace=NAMESPACE,
        expected_sequence=1,
        expected_previous_event_sha256=PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        expected_event_sha256=hashlib.sha256(b"x").hexdigest(),
        expected_request_sha256="a" * 64,
        expected_idempotency_key="b" * 64,
    )

    assert receipt.sequence == 1
    assert receipt.receipt_bytes == FIXED_VECTOR_RECEIPT_BODY


def test_signed_head_rollback_and_fork_are_rejected() -> None:
    private_key = Ed25519PrivateKey.generate()
    transport = _SignedWitnessTransport(private_key)
    client = _client(private_key, transport)
    first = client.compare_and_append(
        namespace=NAMESPACE,
        expected_sequence=0,
        expected_event_sha256=PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        event_bytes=b"first",
    )
    client.compare_and_append(
        namespace=NAMESPACE,
        expected_sequence=1,
        expected_event_sha256=first.event_sha256,
        event_bytes=b"second",
    )

    transport.latest_override = (
        1,
        PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        b"first",
        transport._clock(1),
    )
    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_SIGNED_HEAD_ROLLBACK",
    ):
        client.read_latest(namespace=NAMESPACE)

    private_key = Ed25519PrivateKey.generate()
    transport = _SignedWitnessTransport(private_key)
    client = _client(private_key, transport)
    client.compare_and_append(
        namespace=NAMESPACE,
        expected_sequence=0,
        expected_event_sha256=PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        event_bytes=b"first",
    )
    transport.latest_override = (
        1,
        PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        b"fork",
        transport._clock(1),
    )
    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_SIGNED_HEAD_FORK",
    ):
        client.read_latest(namespace=NAMESPACE)

    private_key = Ed25519PrivateKey.generate()
    transport = _SignedWitnessTransport(private_key)
    client = _client(private_key, transport)
    client.compare_and_append(
        namespace=NAMESPACE,
        expected_sequence=0,
        expected_event_sha256=PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        event_bytes=b"same-event",
    )
    transport.latest_override = (
        1,
        PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        b"same-event",
        "2026-07-22T13:00:09.000000Z",
    )
    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_SIGNED_HEAD_FORK",
    ):
        client.read_latest(namespace=NAMESPACE)


@pytest.mark.parametrize(
    "field,value",
    [
        ("event_sha256", "0" * 64),
        ("request_sha256", "0" * 64),
        ("idempotency_key", "0" * 64),
        ("previous_event_sha256", "0" * 64),
        ("sequence", 7),
    ],
)
def test_compare_append_rejects_signed_but_wrong_receipt_binding(
    field: str,
    value: object,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    transport = _SignedWitnessTransport(private_key)
    transport.receipt_mutator = lambda material: material.__setitem__(field, value)
    client = _client(private_key, transport)

    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_RECEIPT_BINDING_INVALID",
    ):
        client.compare_and_append(
            namespace=NAMESPACE,
            expected_sequence=0,
            expected_event_sha256=PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
            event_bytes=b"event",
        )


def test_compare_append_rejects_signed_readback_substitution() -> None:
    private_key = Ed25519PrivateKey.generate()
    transport = _SignedWitnessTransport(private_key)
    transport.readback_mutator = lambda material: material.update(
        {
            "event_base64": base64.b64encode(b"substitute").decode("ascii"),
            "event_byte_count": len(b"substitute"),
            "event_sha256": hashlib.sha256(b"substitute").hexdigest(),
        }
    )
    client = _client(private_key, transport)

    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_APPEND_EVENT_READBACK_MISMATCH",
    ):
        client.compare_and_append(
            namespace=NAMESPACE,
            expected_sequence=0,
            expected_event_sha256=PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
            event_bytes=b"event",
        )


def test_ambiguous_post_retries_same_idempotency_without_duplicate_append() -> None:
    private_key = Ed25519PrivateKey.generate()
    transport = _SignedWitnessTransport(private_key)
    transport.fail_after_append_once = True
    client = _client(private_key, transport)
    inputs = {
        "namespace": NAMESPACE,
        "expected_sequence": 0,
        "expected_event_sha256": PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        "event_bytes": b"exact-retry",
    }

    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_HTTP_TRANSPORT_FAILED:ReadTimeout",
    ):
        client.compare_and_append(**inputs)
    receipt = client.compare_and_append(**inputs)

    post_requests = [request for request in transport.requests if request[0] == "POST"]
    assert len(transport.events) == 1
    assert len(post_requests) == 2
    assert post_requests[0][2:] == post_requests[1][2:]
    assert receipt.sequence == 1


def test_exact_signed_receipt_can_be_reverified_after_restart() -> None:
    private_key = Ed25519PrivateKey.generate()
    transport = _SignedWitnessTransport(private_key)
    client = _client(private_key, transport)
    event_bytes = b"persisted-receipt"
    receipt = client.compare_and_append(
        namespace=NAMESPACE,
        expected_sequence=0,
        expected_event_sha256=PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        event_bytes=event_bytes,
    )
    post = next(request for request in transport.requests if request[0] == "POST")
    request_bytes = post[2]
    idempotency_key = post[3]
    assert request_bytes is not None and idempotency_key is not None

    restarted_client = _client(private_key, transport)
    reverified = restarted_client.verify_append_receipt_envelope(
        signed_receipt_envelope_bytes=receipt.receipt_bytes,
        expected_namespace=NAMESPACE,
        expected_sequence=1,
        expected_previous_event_sha256=PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        expected_event_sha256=hashlib.sha256(event_bytes).hexdigest(),
        expected_request_sha256=hashlib.sha256(request_bytes).hexdigest(),
        expected_idempotency_key=idempotency_key,
    )

    assert reverified == receipt
    assert json.loads(receipt.receipt_bytes)["signature_hex"]


def test_signed_receipt_rejects_boolean_sequence() -> None:
    private_key = Ed25519PrivateKey.generate()
    transport = _SignedWitnessTransport(private_key)
    transport.receipt_mutator = lambda material: material.__setitem__("sequence", True)
    client = _client(private_key, transport)

    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_RECEIPT_SEQUENCE_INVALID",
    ):
        client.compare_and_append(
            namespace=NAMESPACE,
            expected_sequence=0,
            expected_event_sha256=PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
            event_bytes=b"event",
        )


@pytest.mark.parametrize(
    "base_url",
    [
        "http://witness.example/v1",
        "https://user:password@witness.example/v1",
        "https://witness.example/v1?query=1",
        "https://witness.example/v1#fragment",
        "https://witness.example/a/../v1",
        "https://witness.example/%2e%2e/v1",
        "https://witness.example:bad/v1",
        "https://witness.example:70000/v1",
        "https://witness.example:0/v1",
        "https://witness.example/v1\\ambiguous",
        "https://例え.テスト/v1",
        " https://witness.example/v1",
    ],
)
def test_https_transport_rejects_unauthenticated_or_ambiguous_base_url(
    base_url: str,
) -> None:
    with pytest.raises(ProfiledTrainingExternalWitnessClientV1Error):
        ProfiledTrainingExternalWitnessHttpsTransportV1(
            base_url=base_url,
            bearer_token=TOKEN,
            timeout_seconds=5,
        )


def test_https_transport_rejects_non_mock_transport_escape_hatch() -> None:
    raw_transport = httpx.HTTPTransport()
    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_TEST_TRANSPORT_INVALID",
    ):
        ProfiledTrainingExternalWitnessHttpsTransportV1(
            base_url="https://witness.example/v1",
            bearer_token=TOKEN,
            timeout_seconds=5,
            _test_http_transport=raw_transport,  # type: ignore[arg-type]
        )
    raw_transport.close()


def test_https_transport_sends_exact_auth_and_idempotency_without_redirects() -> None:
    observed: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["method"] = request.method
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers.get("authorization")
        observed["idempotency"] = request.headers.get("idempotency-key")
        observed["accept_encoding"] = request.headers.get("accept-encoding")
        observed["body"] = request.content
        return httpx.Response(
            200,
            headers={"content-type": "application/json; charset=utf-8"},
            stream=httpx.ByteStream(b"{}"),
        )

    transport = ProfiledTrainingExternalWitnessHttpsTransportV1(
        base_url="https://witness.example/v1/",
        bearer_token=TOKEN,
        timeout_seconds=5,
        _test_http_transport=httpx.MockTransport(handler),
    )
    key = "1" * 64
    result = transport.request(
        method="POST",
        path="/namespaces/profiled-trainer/events:compare-and-append",
        body=b"{}",
        idempotency_key=key,
    )
    transport.close()

    assert result.status_code == 200
    assert observed == {
        "method": "POST",
        "url": (
            "https://witness.example/v1/namespaces/profiled-trainer/"
            "events:compare-and-append"
        ),
        "authorization": f"Bearer {TOKEN}",
        "idempotency": key,
        "accept_encoding": "identity",
        "body": b"{}",
    }


def test_https_transport_never_follows_cross_origin_redirect() -> None:
    observed_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_urls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "https://attacker.example/capture"},
            stream=httpx.ByteStream(b""),
        )

    transport = ProfiledTrainingExternalWitnessHttpsTransportV1(
        base_url="https://witness.example/v1",
        bearer_token=TOKEN,
        timeout_seconds=5,
        _test_http_transport=httpx.MockTransport(handler),
    )
    response = transport.request(
        method="GET",
        path="/namespaces/profiled-trainer/latest",
        body=None,
        idempotency_key=None,
    )
    transport.close()

    assert response.status_code == 302
    assert observed_urls == [
        "https://witness.example/v1/namespaces/profiled-trainer/latest"
    ]


def test_https_transport_rejects_wrong_content_type() -> None:
    transport = ProfiledTrainingExternalWitnessHttpsTransportV1(
        base_url="https://witness.example/v1",
        bearer_token=TOKEN,
        timeout_seconds=5,
        _test_http_transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                stream=httpx.ByteStream(b"{}"),
            )
        ),
    )
    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_HTTP_CONTENT_TYPE_INVALID",
    ):
        transport.request(
            method="GET",
            path="/namespaces/profiled-trainer/latest",
            body=None,
            idempotency_key=None,
        )
    transport.close()


def test_https_transport_rejects_encoded_response_before_decoding() -> None:
    transport = ProfiledTrainingExternalWitnessHttpsTransportV1(
        base_url="https://witness.example/v1",
        bearer_token=TOKEN,
        timeout_seconds=5,
        _test_http_transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={
                    "content-encoding": "gzip",
                    "content-type": "application/json",
                },
                stream=_ChunkStream(b"compressed"),
            )
        ),
    )
    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_HTTP_CONTENT_ENCODING_INVALID",
    ):
        transport.request(
            method="GET",
            path="/namespaces/profiled-trainer/latest",
            body=None,
            idempotency_key=None,
        )
    transport.close()


def test_https_transport_bounds_stream_before_concatenation() -> None:
    transport = ProfiledTrainingExternalWitnessHttpsTransportV1(
        base_url="https://witness.example/v1",
        bearer_token=TOKEN,
        timeout_seconds=5,
        _test_http_transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_ChunkStream(b"x" * MAX_PROFILED_WITNESS_WIRE_BYTES, b"x"),
            )
        ),
    )
    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_HTTP_RESPONSE_TOO_LARGE",
    ):
        transport.request(
            method="GET",
            path="/namespaces/profiled-trainer/latest",
            body=None,
            idempotency_key=None,
        )
    transport.close()


def test_json_structure_is_bounded_before_materialization() -> None:
    private_key = Ed25519PrivateKey.generate()
    raw = b'{"x":[' + (b"0," * 32_768) + b"0]}"
    response = ProfiledTrainingExternalWitnessWireResponseV1(
        status_code=200,
        content_type="application/json",
        body=raw,
    )
    client = _client(private_key, _StaticTransport(response))

    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_EVENT_JSON_INVALID",
    ):
        client.read_latest(namespace=NAMESPACE)


def test_wire_response_rejects_oversized_body() -> None:
    with pytest.raises(ProfiledTrainingExternalWitnessClientV1Error):
        ProfiledTrainingExternalWitnessWireResponseV1(
            status_code=200,
            content_type="application/json",
            body=b"x" * (MAX_PROFILED_WITNESS_WIRE_BYTES + 1),
        )


def test_client_context_closes_explicitly_owned_transport() -> None:
    private_key = Ed25519PrivateKey.generate()
    transport = _CloseableStaticTransport(
        ProfiledTrainingExternalWitnessWireResponseV1(
            status_code=404,
            content_type="",
            body=b"",
        )
    )
    with PinnedProfiledTrainingExternalWitnessClientV1(
        transport=transport,
        witness_id=WITNESS_ID,
        witness_public_key_bytes=_raw_public_key(private_key),
        expected_witness_public_key_sha256=hashlib.sha256(
            _raw_public_key(private_key)
        ).hexdigest(),
        close_transport_on_close=True,
    ):
        pass

    assert transport.closed is True


def test_production_client_contains_no_private_signing_primitive() -> None:
    source = (
        Path(__file__).resolve().parents[6]
        / "v2/backend/app/services/native_trainer/"
        "profiled_training_external_witness_client_v1.py"
    ).read_text(encoding="utf-8")

    assert "Ed25519PrivateKey" not in source
    assert ".sign(" not in source
    assert "order_submission_authorized\": True" not in source
    assert "runtime_wired\": True" not in source
