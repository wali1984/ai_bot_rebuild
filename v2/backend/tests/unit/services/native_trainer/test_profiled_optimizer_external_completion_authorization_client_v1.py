from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from v2.backend.app.services.native_trainer import (
    profiled_optimizer_external_completion_authorization_client_v1 as client_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_optimizer_external_completion_authorization_journal_v1 as journal_module,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_optimizer_external_completion_request_v1 as request_support,
)

adapter_evidence = request_support.adapter_evidence
TEST_BEARER_TOKEN = "unit-bearer-token-123456"  # noqa: S105 - inert test credential
PinnedClient = client_module.PinnedProfiledOptimizerCompletionAuthorizationClientV1
ClientError = client_module.ProfiledOptimizerCompletionAuthorizationClientV1Error
HttpsTransport = client_module.ProfiledOptimizerCompletionAuthorizationHttpsTransportV1
WireResponse = client_module.ProfiledOptimizerCompletionAuthorizationWireResponseV1
ProfiledOptimizerCompletionAuthorizationJournalV1 = (
    journal_module.ProfiledOptimizerCompletionAuthorizationJournalV1
)


@dataclass
class _RecordingTransport:
    response: Any
    requests: list[dict[str, Any]] = field(default_factory=list)
    closed: bool = False

    def request(
        self,
        *,
        method: str,
        path: str,
        body: bytes,
        idempotency_key: str,
    ) -> Any:
        self.requests.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "idempotency_key": idempotency_key,
            }
        )
        return self.response

    def close(self) -> None:
        self.closed = True


def _bundle(evidence: dict[str, Any]) -> tuple[Any, bytes, _RecordingTransport, Any]:
    prepared = request_support._prepared(evidence)
    envelope = request_support._signed_envelope(prepared)
    transport = _RecordingTransport(
        WireResponse(
            status_code=200,
            content_type="application/json",
            body=envelope,
        )
    )
    client = PinnedClient(
        transport=transport,
        witness_id=prepared.witness_id,
        witness_public_key_bytes=evidence["public_key"],
        expected_witness_public_key_sha256=evidence["public_key_sha256"],
    )
    return prepared, envelope, transport, client


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def test_dispatch_posts_exact_durable_request_to_purpose_specific_route(
    adapter_evidence: dict[str, Any],
) -> None:
    prepared, envelope, transport, client = _bundle(adapter_evidence)
    verified = client.dispatch_prepared_authorization(prepared)

    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request == {
        "method": "POST",
        "path": (
            "/namespaces/unit%2Fprofiled-optimizer-completion/"
            "completion-authorizations:compare-and-authorize"
        ),
        "body": prepared.request_bytes,
        "idempotency_key": prepared.idempotency_key,
    }
    assert verified.authorization_envelope_sha256 == hashlib.sha256(envelope).hexdigest()
    assert verified.profiled_optimizer_admission_authorized is True
    assert verified.optimizer_execution_authorized is False
    assert verified.checkpoint_write_authorized is False
    assert verified.live_execution_authorized is False


def test_ambiguous_retry_replays_byte_identical_request_and_response(
    adapter_evidence: dict[str, Any],
) -> None:
    prepared, _envelope, transport, client = _bundle(adapter_evidence)
    first = client.dispatch_prepared_authorization(prepared)
    replay = client.dispatch_prepared_authorization(prepared)

    assert replay == first
    assert len(transport.requests) == 2
    assert transport.requests[0] == transport.requests[1]


def test_offline_envelope_verification_performs_no_transport(
    adapter_evidence: dict[str, Any],
) -> None:
    prepared, envelope, transport, client = _bundle(adapter_evidence)
    verified = client.verify_authorization_envelope(
        prepared=prepared,
        authorization_envelope_bytes=envelope,
    )
    assert verified.authorization_sequence == 1
    assert transport.requests == []


def test_changed_witness_identity_or_key_fails_before_transport(
    adapter_evidence: dict[str, Any],
) -> None:
    prepared, envelope, transport, _client = _bundle(adapter_evidence)
    with pytest.raises(ClientError, match="WITNESS_KEY_MISMATCH"):
        PinnedClient(
            transport=transport,
            witness_id=prepared.witness_id,
            witness_public_key_bytes=adapter_evidence["public_key"],
            expected_witness_public_key_sha256=hashlib.sha256(b"wrong-key").hexdigest(),
        )
    changed_id_client = PinnedClient(
        transport=transport,
        witness_id="unit/another-witness",
        witness_public_key_bytes=adapter_evidence["public_key"],
        expected_witness_public_key_sha256=adapter_evidence["public_key_sha256"],
    )
    with pytest.raises(ClientError, match="PREPARED_WITNESS_MISMATCH"):
        changed_id_client.dispatch_prepared_authorization(prepared)
    assert transport.requests == []
    assert envelope


def test_nonexact_prepared_type_and_response_type_fail_closed(
    adapter_evidence: dict[str, Any],
) -> None:
    prepared, _envelope, transport, client = _bundle(adapter_evidence)
    with pytest.raises(ClientError, match="PREPARED_TYPE_INVALID"):
        client.dispatch_prepared_authorization(object())  # type: ignore[arg-type]
    transport.response = {
        "status_code": 200,
        "content_type": "application/json",
        "body": b"{}",
    }
    with pytest.raises(ClientError, match="RESPONSE_TYPE_INVALID"):
        client.dispatch_prepared_authorization(prepared)


@pytest.mark.parametrize(
    ("status_code", "content_type", "reason"),
    (
        (409, "application/json", "HTTP_STATUS_INVALID"),
        (200, "text/plain", "CONTENT_TYPE_INVALID"),
        (307, "application/json", "HTTP_STATUS_INVALID"),
    ),
)
def test_status_redirect_and_content_type_fail_closed(
    adapter_evidence: dict[str, Any],
    status_code: int,
    content_type: str,
    reason: str,
) -> None:
    prepared, envelope, transport, client = _bundle(adapter_evidence)
    transport.response = WireResponse(
        status_code=status_code,
        content_type=content_type,
        body=envelope,
    )
    with pytest.raises(ClientError, match=reason):
        client.dispatch_prepared_authorization(prepared)


def test_altered_or_noncanonical_signed_response_is_rejected(
    adapter_evidence: dict[str, Any],
) -> None:
    prepared, envelope, transport, client = _bundle(adapter_evidence)
    altered = json.loads(envelope)
    altered["authorization_challenge_sha256"] = hashlib.sha256(
        b"changed-challenge"
    ).hexdigest()
    transport.response = WireResponse(
        status_code=200,
        content_type="application/json",
        body=_canonical(altered),
    )
    with pytest.raises(ClientError, match="RESPONSE_UNVERIFIED"):
        client.dispatch_prepared_authorization(prepared)
    transport.response = WireResponse(
        status_code=200,
        content_type="application/json",
        body=envelope + b" ",
    )
    with pytest.raises(ClientError, match="RESPONSE_UNVERIFIED"):
        client.dispatch_prepared_authorization(prepared)


def test_client_and_journal_compose_without_granting_downstream_authority(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    prepared, envelope, _transport, client = _bundle(adapter_evidence)
    journal = ProfiledOptimizerCompletionAuthorizationJournalV1(
        (tmp_path / "authorization-journal.sqlite3").absolute(),
        immutable_store=ImmutableSourcePayloadStore(
            (tmp_path / "authorization-cas").absolute()
        ),
    )
    pending = journal.persist_prepared_request(
        prepared=prepared,
        witness_public_key_bytes=client.witness_public_key_bytes,
    )
    verified = client.dispatch_prepared_authorization(pending.prepared)
    anchored = journal.commit_authorization_anchored(
        operation_id=pending.operation_id,
        authorization_envelope_bytes=envelope,
        witness_public_key_bytes=client.witness_public_key_bytes,
    )
    assert anchored.verified == verified
    assert anchored.verified is not None
    assert anchored.verified.profiled_optimizer_admission_authorized is True
    assert anchored.verified.optimizer_execution_authorized is False
    assert anchored.verified.runtime_wired is False


@pytest.mark.parametrize(
    "base_url",
    (
        "http://witness.example",
        "https://user:password@witness.example",
        "https://witness.example/path/../escape",
        "https://witness.example/api/./v1",
        "https://witness.example/api//",
        "https://witness.example?query=1",
        "https://witness.example/#fragment",
        " https://witness.example",
        "https://wit\nness.example",
    ),
)
def test_https_transport_rejects_unsafe_base_urls(base_url: str) -> None:
    with pytest.raises(ClientError, match="BASE_URL_INVALID"):
        HttpsTransport(
            base_url=base_url,
            bearer_token=TEST_BEARER_TOKEN,
            timeout_seconds=5.0,
        )


def test_https_transport_sends_pinned_headers_and_exact_body(
    adapter_evidence: dict[str, Any],
) -> None:
    prepared = request_support._prepared(adapter_evidence)
    envelope = request_support._signed_envelope(prepared)
    observed: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["method"] = request.method
        observed["url"] = str(request.url)
        observed["headers"] = dict(request.headers)
        observed["body"] = request.content
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=httpx.ByteStream(envelope),
        )

    transport = HttpsTransport(
        base_url="https://witness.example/api/v1",
        bearer_token=TEST_BEARER_TOKEN,
        timeout_seconds=5.0,
        _test_http_transport=httpx.MockTransport(handler),
    )
    client = PinnedClient(
        transport=transport,
        witness_id=prepared.witness_id,
        witness_public_key_bytes=adapter_evidence["public_key"],
        expected_witness_public_key_sha256=adapter_evidence["public_key_sha256"],
        close_transport_on_close=True,
    )
    with client:
        client.dispatch_prepared_authorization(prepared)

    assert observed["method"] == "POST"
    assert observed["url"].endswith(
        "/api/v1/namespaces/unit%2Fprofiled-optimizer-completion/"
        "completion-authorizations:compare-and-authorize"
    )
    assert observed["headers"]["authorization"] == f"Bearer {TEST_BEARER_TOKEN}"
    assert observed["headers"]["accept-encoding"] == "identity"
    assert observed["headers"]["idempotency-key"] == prepared.idempotency_key
    assert observed["body"] == prepared.request_bytes


@pytest.mark.parametrize(
    ("response_headers", "response_body", "reason"),
    (
        ({"Content-Type": "text/plain"}, b"not-json", "CONTENT_TYPE_INVALID"),
        (
            {"Content-Type": "application/json", "Content-Encoding": "gzip"},
            b"compressed",
            "CONTENT_ENCODING_INVALID",
        ),
    ),
)
def test_https_transport_rejects_content_smuggling(
    adapter_evidence: dict[str, Any],
    response_headers: dict[str, str],
    response_body: bytes,
    reason: str,
) -> None:
    prepared = request_support._prepared(adapter_evidence)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers=response_headers,
            stream=httpx.ByteStream(response_body),
        )

    transport = HttpsTransport(
        base_url="https://witness.example",
        bearer_token=TEST_BEARER_TOKEN,
        timeout_seconds=5.0,
        _test_http_transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ClientError, match=reason):
        transport.request(
            method="POST",
            path="/namespaces/unit/completion-authorizations:compare-and-authorize",
            body=prepared.request_bytes,
            idempotency_key=prepared.idempotency_key,
        )


@pytest.mark.parametrize(
    ("method", "path", "idempotency_key", "reason"),
    (
        (
            "GET",
            "/namespaces/unit/completion-authorizations:compare-and-authorize",
            "1" * 64,
            "HTTP_METHOD_INVALID",
        ),
        ("POST", "/namespaces/unit/latest", "1" * 64, "HTTP_PATH_INVALID"),
        (
            "POST",
            "/namespaces/unit%2fescape/completion-authorizations:compare-and-authorize",
            "1" * 64,
            "HTTP_PATH_INVALID",
        ),
        (
            "POST",
            "/namespaces/unit/completion-authorizations:compare-and-authorize",
            "not-a-sha",
            "IDEMPOTENCY_INVALID",
        ),
        (
            "POST",
            "/namespaces/./completion-authorizations:compare-and-authorize",
            "1" * 64,
            "HTTP_PATH_INVALID",
        ),
        (
            "POST",
            "/namespaces/%2E%2E/completion-authorizations:compare-and-authorize",
            "1" * 64,
            "HTTP_PATH_INVALID",
        ),
        (
            "POST",
            "/namespaces/%00/completion-authorizations:compare-and-authorize",
            "1" * 64,
            "HTTP_PATH_INVALID",
        ),
        (
            "POST",
            "/namespaces/%61/completion-authorizations:compare-and-authorize",
            "1" * 64,
            "HTTP_PATH_INVALID",
        ),
        (
            "POST",
            "/namespaces/%2F/completion-authorizations:compare-and-authorize",
            "1" * 64,
            "HTTP_PATH_INVALID",
        ),
    ),
)
def test_https_transport_accepts_only_exact_purpose_route_and_identity(
    method: str,
    path: str,
    idempotency_key: str,
    reason: str,
) -> None:
    transport = HttpsTransport(
        base_url="https://witness.example",
        bearer_token=TEST_BEARER_TOKEN,
        timeout_seconds=5.0,
        _test_http_transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                500,
                headers={"Content-Type": "application/json"},
                stream=httpx.ByteStream(b"{}"),
            )
        ),
    )
    with pytest.raises(ClientError, match=reason):
        transport.request(
            method=method,
            path=path,
            body=b"{}",
            idempotency_key=idempotency_key,
        )


def test_https_transport_bounds_response_before_client_parsing(
    adapter_evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = request_support._prepared(adapter_evidence)
    wire_limit = len(prepared.request_bytes)
    monkeypatch.setattr(
        client_module,
        "MAX_COMPLETION_AUTHORIZATION_WIRE_BYTES",
        wire_limit,
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=httpx.ByteStream(b"x" * (wire_limit + 1)),
        )

    transport = HttpsTransport(
        base_url="https://witness.example",
        bearer_token=TEST_BEARER_TOKEN,
        timeout_seconds=5.0,
        _test_http_transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ClientError, match="RESPONSE_TOO_LARGE"):
        transport.request(
            method="POST",
            path="/namespaces/unit/completion-authorizations:compare-and-authorize",
            body=prepared.request_bytes,
            idempotency_key=prepared.idempotency_key,
        )


def test_transport_ownership_closes_exactly_when_requested(
    adapter_evidence: dict[str, Any],
) -> None:
    prepared, _envelope, transport, _client = _bundle(adapter_evidence)
    client = PinnedClient(
        transport=transport,
        witness_id=prepared.witness_id,
        witness_public_key_bytes=adapter_evidence["public_key"],
        expected_witness_public_key_sha256=adapter_evidence["public_key_sha256"],
        close_transport_on_close=True,
    )
    client.close()
    client.close()
    assert transport.closed is True
    with pytest.raises(ClientError, match="CLIENT_CLOSED"):
        client.dispatch_prepared_authorization(prepared)


def test_module_has_no_private_signer_head_routes_optimizer_or_trading_authority() -> None:
    module_path = (
        Path(__file__).resolve().parents[6]
        / "v2/backend/app/services/native_trainer/"
        "profiled_optimizer_external_completion_authorization_client_v1.py"
    )
    source = module_path.read_text(encoding="utf-8")

    assert "Ed25519PrivateKey" not in source
    assert "events:compare-and-append" not in source
    assert '"latest"' not in source
    assert "profiled_training_external_witness_client_v1" not in source
    assert "optimizer.step" not in source
    assert "torch.save" not in source
    assert "submit_order" not in source
