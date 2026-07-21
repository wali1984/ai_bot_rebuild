from __future__ import annotations

import base64
import gzip
import hashlib
import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from app.services.smart_money_wallets import publisher as publisher_module
from app.services.smart_money_wallets.client import MoralisClient
from app.services.smart_money_wallets.endpoint_registry import (
    MoralisEndpointSpec,
    moralis_endpoint_registry,
)
from app.services.smart_money_wallets.models import (
    MAX_MORALIS_RAW_RESPONSE_BYTES,
    MORALIS_RAW_RESPONSE_BYTES_SCOPE,
    MoralisResponse,
)
from app.services.smart_money_wallets.publisher import publish_moralis_result

_TOKEN = "0x" + ("1" * 40)
_TRANSPORT_STARTED_AT = "2026-07-20T12:00:00.000001Z"
_OBSERVED_AT = "2026-07-20T12:00:00.000002Z"
_INGESTED_AT = "2026-07-20T12:00:00.000003Z"
_GENERATED_AT = "2026-07-20T12:00:00.000004Z"


class _FakeLimiter:
    def allow_request(self, *, estimated_cu: int) -> SimpleNamespace:
        assert estimated_cu > 0
        return SimpleNamespace(allowed=True, reservation=object())

    def observe_response(self, status_code: int | None) -> None:
        assert status_code is None or isinstance(status_code, int)

    def reconcile_response(self, **kwargs: Any) -> SimpleNamespace:
        assert kwargs["http_status"] is not None
        return SimpleNamespace(applied=True, reason=None)

    def retain_ambiguous_reservation(self, reservation: object) -> None:
        del reservation

    def refund_pending(self, *, request_was_not_sent: bool = False) -> int:
        return int(request_was_not_sent)


class _TrackingChunks:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self.chunks = chunks
        self.consumed_chunks = 0

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self.chunks:
            self.consumed_chunks += 1
            yield chunk


class _GetOnlyHttpClient:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, *_args: Any, **_kwargs: Any) -> httpx.Response:
        self.calls += 1
        raise AssertionError("unbounded get fallback must not be called")


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def ttl(self, key: str) -> int:
        if key not in self.data:
            return -2
        return self.ttls.get(key, -1)

    def eval(self, script: str, numkeys: int, *args: object) -> int:
        assert numkeys == 1
        assert "MORALIS_AGGREGATE_CAS_V1" in script
        key, expected_exists, expected_raw, replacement, ttl = map(str, args)
        current = self.data.get(key)
        if expected_exists == "0":
            if current is not None:
                return 0
        elif current != expected_raw:
            return 0
        self.data[key] = replacement
        self.ttls[key] = int(ttl)
        return 1


def _spec(endpoint_id: str) -> MoralisEndpointSpec:
    return next(spec for spec in moralis_endpoint_registry() if spec.endpoint_id == endpoint_id)


def _clock_factory() -> Callable[[], datetime]:
    first = datetime(2026, 7, 20, 12, tzinfo=UTC)
    values = iter(first + timedelta(microseconds=index) for index in (1, 2, 3))
    return lambda: next(values)


def _client_response(raw: bytes, *, status_code: int = 200) -> MoralisResponse:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("https://deep-index.moralis.io/api/v2.2/")
        assert request.headers["accept"] == "application/json"
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            status_code,
            headers={"content-length": str(len(raw))},
            stream=httpx.ByteStream(raw),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        return MoralisClient(
            api_key="fixture-key",  # noqa: S106 - non-secret test fixture
            limiter=_FakeLimiter(),  # type: ignore[arg-type]
            http_client=http_client,
            now_factory=_clock_factory(),
        ).get(_spec("token_price"), chain="eth", token=_TOKEN, symbol="LINKUSDT")


def _client_stream_response(
    stream: Iterable[bytes],
    *,
    response_headers: dict[str, str] | None = None,
) -> MoralisResponse:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("https://deep-index.moralis.io/api/v2.2/")
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, headers=response_headers, content=stream)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        return MoralisClient(
            api_key="fixture-key",  # noqa: S106 - non-secret test fixture
            limiter=_FakeLimiter(),  # type: ignore[arg-type]
            http_client=http_client,
            now_factory=_clock_factory(),
        ).get(_spec("token_price"), chain="eth", token=_TOKEN, symbol="LINKUSDT")


def _publish_response(
    redis_client: _FakeRedis,
    response: MoralisResponse,
    *,
    raw_response_sha256: str | None = None,
    ingested_at: str | None = None,
    generated_at: str = _GENERATED_AT,
) -> dict[str, Any]:
    return publish_moralis_result(
        redis_client,
        env={"MORALIS_API_KEY": "fixture-key"},
        spec=_spec("token_price"),
        chain="eth",
        symbol="LINKUSDT",
        token=_TOKEN,
        http_status=response.http_status,
        payload=response.payload,
        budget_status={"compute_budget": {"used_today": 50, "used_month": 50}},
        error_class=response.error_class,
        raw_response_bytes=response.raw_response_bytes,
        raw_response_sha256=(
            response.raw_response_sha256 if raw_response_sha256 is None else raw_response_sha256
        ),
        raw_response_byte_count=response.raw_response_byte_count,
        raw_response_bytes_scope=response.raw_response_bytes_scope,
        transport_started_at=response.transport_started_at,
        observed_at=response.observed_at,
        ingested_at=response.ingested_at if ingested_at is None else ingested_at,
        generated_at=generated_at,
    )


def test_client_captures_immutable_exact_application_visible_bytes_and_clocks() -> None:
    raw = (
        b'{ "usdPrice": 12.5, '
        b'"block_timestamp": "2026-07-20T11:59:59Z", "label": "\xe2\x82\xac" }'
    )
    response = _client_response(raw)

    assert response.ok is True
    assert response.raw_response_bytes == raw
    assert response.raw_response_sha256 == hashlib.sha256(raw).hexdigest()
    assert response.raw_response_byte_count == len(raw)
    assert response.raw_response_bytes_scope == MORALIS_RAW_RESPONSE_BYTES_SCOPE
    assert response.transport_started_at == _TRANSPORT_STARTED_AT
    assert response.observed_at == _OBSERVED_AT
    assert response.ingested_at == _INGESTED_AT
    assert response.available_at is None
    assert response.payload["label"] == "€"
    with pytest.raises(FrozenInstanceError):
        response.raw_response_bytes = b"tampered"  # type: ignore[misc]


def test_client_accepts_an_exactly_at_cap_identity_body() -> None:
    prefix = b'{"value":"'
    suffix = b'"}'
    raw = prefix + (b"x" * (MAX_MORALIS_RAW_RESPONSE_BYTES - len(prefix) - len(suffix))) + suffix

    response = _client_response(raw)

    assert response.ok is True
    assert response.raw_response_bytes == raw
    assert response.raw_response_byte_count == MAX_MORALIS_RAW_RESPONSE_BYTES
    assert response.raw_response_sha256 == hashlib.sha256(raw).hexdigest()
    assert response.ingested_at == _INGESTED_AT


def test_client_rejects_compressed_body_before_decompression_or_stream_consumption() -> None:
    expanded = b"x" * (MAX_MORALIS_RAW_RESPONSE_BYTES * 32)
    stream = _TrackingChunks((gzip.compress(expanded),))

    response = _client_stream_response(
        stream,
        response_headers={"content-encoding": "gzip"},
    )

    assert len(stream.chunks[0]) < MAX_MORALIS_RAW_RESPONSE_BYTES
    assert response.ok is False
    assert response.error_class == "RAW_RESPONSE_CONTENT_ENCODING_UNSUPPORTED"
    assert response.raw_response_bytes is None
    assert response.raw_response_byte_count is None
    assert response.raw_response_sha256 is None
    assert response.observed_at == _OBSERVED_AT
    assert response.ingested_at is None
    assert stream.consumed_chunks == 0


def test_client_rejects_declared_oversize_before_body_stream_consumption() -> None:
    stream = _TrackingChunks((b"must-not-be-consumed",))

    response = _client_stream_response(
        stream,
        response_headers={"content-length": str(MAX_MORALIS_RAW_RESPONSE_BYTES + 1)},
    )

    assert response.error_class == "RAW_RESPONSE_BYTE_LIMIT_EXCEEDED"
    assert response.raw_response_bytes is None
    assert response.ingested_at is None
    assert stream.consumed_chunks == 0


def test_client_fails_closed_before_dispatch_without_bounded_streaming_transport() -> None:
    http_client = _GetOnlyHttpClient()
    response = MoralisClient(
        api_key="fixture-key",  # noqa: S106 - non-secret test fixture
        limiter=_FakeLimiter(),  # type: ignore[arg-type]
        http_client=http_client,  # type: ignore[arg-type]
        now_factory=_clock_factory(),
    ).get(_spec("token_price"), chain="eth", token=_TOKEN, symbol="LINKUSDT")

    assert response.ok is False
    assert response.error_class == "BoundedStreamingRequiredError"
    assert response.request_dispatched is False
    assert response.transport_started_at is None
    assert response.raw_response_bytes is None
    assert response.ingested_at is None
    assert http_client.calls == 0


def test_client_discards_oversized_body_without_zero_filling_or_false_success() -> None:
    stream = _TrackingChunks(
        (
            b"x" * MAX_MORALIS_RAW_RESPONSE_BYTES,
            b"y" * 65_536,
            b"must-not-be-consumed-after-limit",
        )
    )
    response = _client_stream_response(stream)

    assert response.ok is False
    assert response.error_class == "RAW_RESPONSE_BYTE_LIMIT_EXCEEDED"
    assert response.payload is None
    assert response.raw_response_bytes is None
    assert response.raw_response_byte_count is None
    assert response.raw_response_sha256 is None
    assert response.transport_started_at == _TRANSPORT_STARTED_AT
    assert response.observed_at == _OBSERVED_AT
    assert response.ingested_at is None
    assert response.available_at is None
    assert stream.consumed_chunks == 2


def test_client_rejects_duplicate_json_keys_but_retains_bounded_exact_evidence() -> None:
    raw = b'{"usdPrice":1,"usdPrice":2}'
    response = _client_response(raw)

    assert response.ok is False
    assert response.error_class == "RAW_RESPONSE_JSON_INVALID"
    assert response.payload is None
    assert response.raw_response_bytes == raw
    assert response.raw_response_sha256 == hashlib.sha256(raw).hexdigest()


def test_publisher_binds_exact_body_and_distinct_clocks_without_availability_authority() -> None:
    raw = (
        b'{ "usdPrice": 12.5, '
        b'"block_timestamp": "2026-07-20T11:59:59Z", "label": "exact spacing" }'
    )
    response = _client_response(raw)
    redis_client = _FakeRedis()
    result = _publish_response(redis_client, response)

    source_key = next(key for key in result["planned_keys"] if key.startswith("v2:moralis:raw:v2:"))
    source_raw = redis_client.data[source_key]
    source = json.loads(source_raw)
    aggregate = json.loads(redis_client.data["v2:moralis:feature_aggregate:LINKUSDT:1m"])
    endpoint = aggregate["endpoint_payloads"]["token_price"]

    assert base64.b64decode(source["raw_response_body_base64"], validate=True) == raw
    assert source["raw_response_sha256"] == hashlib.sha256(raw).hexdigest()
    assert source["raw_response_byte_count"] == len(raw)
    assert source["raw_response_bytes_scope"] == MORALIS_RAW_RESPONSE_BYTES_SCOPE
    assert source["raw_response_evidence_bound"] is True
    assert source["transport_started_at"] == _TRANSPORT_STARTED_AT
    assert source["observed_at"] == _OBSERVED_AT
    assert source["ingested_at"] == _INGESTED_AT
    assert source["generated_at"] == _GENERATED_AT
    assert source["available_at"] is None
    assert source_key.endswith(hashlib.sha256(source_raw.encode("utf-8")).hexdigest())
    assert endpoint["raw_response_evidence_bound"] is True
    assert endpoint["raw_response_evidence_persisted"] is True
    assert endpoint["ingested_at"] == _INGESTED_AT
    assert aggregate["ingested_at"] == _INGESTED_AT
    assert aggregate["available_at"] is None
    for payload in (result, endpoint, aggregate):
        assert payload["publication_authority"] is False
        assert payload["trainer_authority"] is False
        assert payload["prediction_authority"] is False
        assert payload["risk_authority"] is False
        assert payload["allocator_authority"] is False
        assert payload["paper_authority"] is False
        assert payload["live_authority"] is False


def test_publisher_preserves_valid_raw_json_when_optional_metadata_is_semantically_unsafe() -> None:
    raw = (
        b'{"result":[{"block_timestamp":"2026-07-20T11:59:59Z",'
        b'"token_name":"unsafe\\u200bdisplay-name","value":12.5}]}'
    )
    response = _client_response(raw)
    redis_client = _FakeRedis()

    result = _publish_response(redis_client, response)

    source_key = next(key for key in result["planned_keys"] if key.startswith("v2:moralis:raw:v2:"))
    source = json.loads(redis_client.data[source_key])
    endpoint_status = json.loads(redis_client.data["v2:provider:moralis:endpoint_status"])
    endpoint = endpoint_status["endpoints"]["token_price"]

    assert response.ok is True
    assert result["raw_response_evidence_bound"] is True
    assert result["raw_response_evidence_persisted"] is True
    assert source["raw_response_evidence_bound"] is True
    # The immutable source body is constructed before its write can be
    # acknowledged.  Persistence is asserted by the post-write result and
    # endpoint status, never self-certified inside the source artifact.
    assert source.get("raw_response_evidence_persisted") is not True
    assert base64.b64decode(source["raw_response_body_base64"], validate=True) == raw
    assert source["raw_response_sha256"] == hashlib.sha256(raw).hexdigest()
    assert source["actual_payload_present"] is False
    assert source["semantic_payload_present"] is False
    assert "PAYLOAD_NOT_BOUNDED_CLOSED_JSON" in source["normalization_rejection_reasons"]
    assert endpoint["raw_response_evidence_bound"] is True
    assert endpoint["raw_response_evidence_persisted"] is True
    assert endpoint["source_semantic_claim_count"] == 0
    for payload in (result, source, endpoint):
        assert payload["publication_authority"] is False
        assert payload["trainer_authority"] is False
        assert payload["prediction_authority"] is False
        assert payload["risk_authority"] is False
        assert payload["allocator_authority"] is False
        assert payload["paper_authority"] is False
        assert payload["live_authority"] is False


def test_publisher_marks_digest_mismatch_unbound_and_never_repairs_the_claim() -> None:
    response = _client_response(b'{"usdPrice":12.5,"block_timestamp":"2026-07-20T11:59:59Z"}')
    redis_client = _FakeRedis()
    result = _publish_response(redis_client, response, raw_response_sha256="0" * 64)
    source_key = next(key for key in result["planned_keys"] if key.startswith("v2:moralis:raw:v2:"))
    source = json.loads(redis_client.data[source_key])

    assert result["raw_response_evidence_bound"] is False
    assert result["raw_response_evidence_persisted"] is False
    assert "RAW_RESPONSE_SHA256_MISMATCH" in result["raw_response_evidence_rejection_reasons"]
    assert "raw_response_body_base64" not in source
    assert result["available_at"] is None
    assert result["trainer_authority"] is False
    assert result["live_authority"] is False


def test_publisher_rejects_byte_count_and_scope_claim_mismatches() -> None:
    response = _client_response(b'{"usdPrice":12.5,"block_timestamp":"2026-07-20T11:59:59Z"}')
    cases = (
        (
            replace(response, raw_response_byte_count=len(response.raw_response_bytes or b"") + 1),
            "RAW_RESPONSE_BYTE_COUNT_MISMATCH",
        ),
        (
            replace(response, raw_response_bytes_scope="UNTRUSTED_WIRE_SCOPE"),
            "RAW_RESPONSE_BYTES_SCOPE_INVALID",
        ),
    )

    for forged, expected_reason in cases:
        redis_client = _FakeRedis()
        result = _publish_response(redis_client, forged)

        assert result["raw_response_evidence_bound"] is False
        assert result["raw_response_evidence_persisted"] is False
        assert expected_reason in result["raw_response_evidence_rejection_reasons"]
        assert result["available_at"] is None
        assert result["trainer_authority"] is False
        assert result["live_authority"] is False


def test_publisher_rejects_raw_body_to_parsed_payload_divergence() -> None:
    response = _client_response(b'{"usdPrice":12.5,"block_timestamp":"2026-07-20T11:59:59Z"}')
    forged = replace(
        response,
        payload={"usdPrice": 999.0, "block_timestamp": "2026-07-20T11:59:59Z"},
    )
    redis_client = _FakeRedis()
    result = _publish_response(redis_client, forged)

    assert result["raw_response_evidence_bound"] is False
    assert result["raw_response_evidence_persisted"] is False
    assert (
        "RAW_RESPONSE_PARSED_PAYLOAD_MISMATCH" in result["raw_response_evidence_rejection_reasons"]
    )
    assert result["available_at"] is None
    assert result["trainer_authority"] is False
    assert result["live_authority"] is False


@pytest.mark.parametrize(
    (
        "transport_started_at",
        "observed_at",
        "ingested_at",
        "generated_at",
        "expected_reason",
    ),
    [
        (
            "2026-07-20T12:00:00.000003Z",
            "2026-07-20T12:00:00.000002Z",
            "2026-07-20T12:00:00.000003Z",
            "2026-07-20T12:00:00.000004Z",
            "TRANSPORT_STARTED_AT_AFTER_OBSERVED_AT",
        ),
        (
            "2026-07-20T12:00:00.000001Z",
            "2026-07-20T12:00:00.000003Z",
            "2026-07-20T12:00:00.000002Z",
            "2026-07-20T12:00:00.000004Z",
            "OBSERVED_AT_AFTER_INGESTED_AT",
        ),
        (
            "2026-07-20T12:00:00.000001Z",
            "2026-07-20T12:00:00.000002Z",
            "2026-07-20T12:00:00.000005Z",
            "2026-07-20T12:00:00.000004Z",
            "INGESTED_AT_AFTER_GENERATED_AT",
        ),
    ],
)
def test_publisher_rejects_all_transport_clock_inversions_without_availability(
    transport_started_at: str,
    observed_at: str,
    ingested_at: str,
    generated_at: str,
    expected_reason: str,
) -> None:
    response = _client_response(b'{"usdPrice":12.5,"block_timestamp":"2026-07-20T11:59:59Z"}')
    response = replace(
        response,
        transport_started_at=transport_started_at,
        observed_at=observed_at,
        ingested_at=ingested_at,
    )
    redis_client = _FakeRedis()
    result = _publish_response(
        redis_client,
        response,
        generated_at=generated_at,
    )

    assert result["raw_response_evidence_bound"] is False
    assert result["raw_response_evidence_persisted"] is False
    assert expected_reason in result["raw_response_evidence_rejection_reasons"]
    assert result["available_at"] is None
    assert result["postcommit_receipt_bound"] is False
    assert result["trainer_authority"] is False
    assert result["live_authority"] is False


def test_persisted_raw_body_tamper_is_detected_by_receipt_integrity_resolution() -> None:
    response = _client_response(b'{"usdPrice":12.5,"block_timestamp":"2026-07-20T11:59:59Z"}')
    redis_client = _FakeRedis()
    result = _publish_response(redis_client, response)
    source_key = next(key for key in result["planned_keys"] if key.startswith("v2:moralis:raw:v2:"))
    source = json.loads(redis_client.data[source_key])
    aggregate = json.loads(redis_client.data["v2:moralis:feature_aggregate:LINKUSDT:1m"])
    endpoint = aggregate["endpoint_payloads"]["token_price"]
    exact_body = bytearray(base64.b64decode(source["raw_response_body_base64"], validate=True))
    exact_body[-1] ^= 1
    source["raw_response_body_base64"] = base64.b64encode(exact_body).decode("ascii")

    reasons = publisher_module._raw_response_receipt_integrity_reasons(endpoint, source)

    assert "RAW_RESPONSE_SHA256_MISMATCH" in reasons
    assert endpoint["raw_response_evidence_bound"] is True
    assert endpoint["trainer_authority"] is False
    assert endpoint["live_authority"] is False


def test_typed_empty_rate_limited_and_deferred_states_never_become_zero_features() -> None:
    empty_response = _client_response(b'{"result":[]}')
    empty_redis = _FakeRedis()
    empty = _publish_response(empty_redis, empty_response)
    empty_source_key = next(
        key for key in empty["planned_keys"] if key.startswith("v2:moralis:raw:v2:")
    )
    empty_source = json.loads(empty_redis.data[empty_source_key])

    assert empty["source_observation_present"] is False
    assert empty["raw_transport_actual_payload_present"] is False
    assert empty["raw_response_evidence_bound"] is True
    assert empty["raw_response_evidence_persisted"] is True
    assert empty_source["features"] == {}
    assert empty_source["diagnostic_features"] == {}
    assert empty_source["source_semantic_claim_count"] == 0
    assert "v2:features:moralis:LINKUSDT:1m" not in empty_redis.data

    rate_response = _client_response(b'{"message":"rate limited"}', status_code=429)
    rate_redis = _FakeRedis()
    rate_limited = _publish_response(rate_redis, rate_response)
    assert rate_limited["status"] == "RATE_LIMITED"
    assert rate_limited["raw_response_byte_count"] == len(b'{"message":"rate limited"}')
    assert rate_limited["raw_response_evidence_persisted"] is False
    assert not any(key.startswith("v2:moralis:raw:v2:") for key in rate_redis.data)
    assert "v2:features:moralis:LINKUSDT:1m" not in rate_redis.data

    deferred_redis = _FakeRedis()
    deferred = publish_moralis_result(
        deferred_redis,
        env={"MORALIS_API_KEY": "fixture-key"},
        spec=_spec("token_price"),
        chain="eth",
        symbol="LINKUSDT",
        token=_TOKEN,
        http_status=None,
        payload=None,
        budget_status={},
        error_class="DURABLE_CADENCE_CLAIM_ACTIVE",
        generated_at=_GENERATED_AT,
    )
    assert deferred["status"] == "CADENCE_DEFERRED"
    assert deferred["source_observation_present"] is False
    assert deferred["raw_response_byte_count"] is None
    assert "v2:features:moralis:LINKUSDT:1m" not in deferred_redis.data
