from __future__ import annotations

import ast
import hashlib
import inspect
import json
import sys
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import atomic_redis_source_reader as reader
from v2.backend.app.services.native_trainer.atomic_redis_source_reader import (
    ATOMIC_REDIS_SOURCE_READ_DOWNSTREAM_STATUS,
    ATOMIC_REDIS_SOURCE_READ_EVIDENCE_CLASSIFICATION,
    ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION,
    ATOMIC_REDIS_SOURCE_RESULT_SCHEMA_VERSION,
    MAX_BATCH_MATERIALIZED_PAYLOAD_BYTES,
    MAX_RANGE_REPLY_BYTES,
    MAX_SOURCE_KEY_BYTES,
    MAX_SOURCE_KEYS_PER_BATCH,
    MAX_SOURCE_PAYLOAD_BYTES,
    REDIS_TIME_CLOCK_SEMANTICS,
    AtomicRedisSourceReadIntegrityError,
    AtomicRedisSourceReadTransportError,
    AtomicRedisSourceReadValidationError,
    read_atomic_redis_sources,
)

KEY_A = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
KEY_B = "v2:market:ohlcv_closed:binance:ETHUSDT:5m"
TIME = (1_784_425_600, 123_456)
HOSTILE_DETAIL = "SENSITIVE_ATOMIC_REDIS_CALLER_SECRET"


class _FakePipeline:
    def __init__(
        self,
        responses: object,
        *,
        command_failure: str | None = None,
        execute_failure: bool = False,
        cleanup_failures: frozenset[str] = frozenset(),
        clear_responses_on_reset: bool = False,
    ) -> None:
        self.responses = responses
        self.command_failure = command_failure
        self.execute_failure = execute_failure
        self.cleanup_failures = cleanup_failures
        self.clear_responses_on_reset = clear_responses_on_reset
        self.commands: list[tuple[object, ...]] = []
        self.reset_calls = 0
        self.close_calls = 0

    def _queue(self, command: str, *arguments: object) -> _FakePipeline:
        self.commands.append((command, *arguments))
        if self.command_failure == command:
            raise RuntimeError(HOSTILE_DETAIL)
        return self

    def type(self, key: str) -> _FakePipeline:
        return self._queue("TYPE", key)

    def getrange(self, key: str, start: int, end: int) -> _FakePipeline:
        return self._queue("GETRANGE", key, start, end)

    def pttl(self, key: str) -> _FakePipeline:
        return self._queue("PTTL", key)

    def time(self) -> _FakePipeline:
        return self._queue("TIME")

    def execute(self) -> object:
        if self.execute_failure:
            raise RuntimeError(HOSTILE_DETAIL)
        return self.responses

    def reset(self) -> None:
        self.reset_calls += 1
        if self.clear_responses_on_reset and type(self.responses) is list:
            self.responses.clear()
        if "reset" in self.cleanup_failures:
            raise RuntimeError(HOSTILE_DETAIL)

    def close(self) -> None:
        self.close_calls += 1
        if "close" in self.cleanup_failures:
            raise RuntimeError(HOSTILE_DETAIL)


class _FakeClient:
    def __init__(
        self,
        responses: object,
        *,
        connection_kwargs: object | None = None,
        command_failure: str | None = None,
        execute_failure: bool = False,
        pipeline_failure: bool = False,
        cleanup_failures: frozenset[str] = frozenset(),
        clear_responses_on_reset: bool = False,
    ) -> None:
        self.connection_kwargs = (
            {"decode_responses": False} if connection_kwargs is None else connection_kwargs
        )
        self.pipeline_failure = pipeline_failure
        self.pipeline_instance = _FakePipeline(
            responses,
            command_failure=command_failure,
            execute_failure=execute_failure,
            cleanup_failures=cleanup_failures,
            clear_responses_on_reset=clear_responses_on_reset,
        )
        self.transactions: list[bool] = []

    def get_connection_kwargs(self) -> dict[str, Any]:
        return self.connection_kwargs  # type: ignore[return-value]

    def pipeline(self, *, transaction: bool) -> _FakePipeline:
        self.transactions.append(transaction)
        if self.pipeline_failure:
            raise RuntimeError(HOSTILE_DETAIL)
        return self.pipeline_instance


def _present(payload: bytes = b'{"exact": 1}\n', pttl_ms: int = 91_337) -> list[object]:
    return [b"string", payload, pttl_ms]


def _missing() -> list[object]:
    return [b"none", b"", -2]


def _client_for(*rows: list[object], time: object = TIME, **kwargs: Any) -> _FakeClient:
    responses: list[object] = []
    for row in rows:
        responses.extend(row)
    responses.append(time)
    return _FakeClient(responses, **kwargs)


def _assert_fixed_error(
    client: _FakeClient,
    keys: object,
    error_type: type[Exception],
    reason: str,
) -> Exception:
    with pytest.raises(error_type) as exc_info:
        read_atomic_redis_sources(client, keys)
    assert str(exc_info.value) == reason
    assert HOSTILE_DETAIL not in str(exc_info.value)
    return exc_info.value


def test_one_transaction_queues_deterministic_read_order_and_time_last() -> None:
    client = _client_for(_present(b"first"), _missing())

    batch = read_atomic_redis_sources(client, [KEY_A, KEY_B])

    assert client.transactions == [True]
    assert client.pipeline_instance.commands == [
        ("TYPE", KEY_A),
        ("GETRANGE", KEY_A, 0, MAX_SOURCE_PAYLOAD_BYTES),
        ("PTTL", KEY_A),
        ("TYPE", KEY_B),
        ("GETRANGE", KEY_B, 0, MAX_SOURCE_PAYLOAD_BYTES),
        ("PTTL", KEY_B),
        ("TIME",),
    ]
    assert tuple(result.source_key for result in batch.results) == (KEY_A, KEY_B)
    assert client.pipeline_instance.reset_calls == 1
    assert client.pipeline_instance.close_calls == 1


def test_exact_non_utf8_bytes_are_retained_unmodified_and_repr_hidden() -> None:
    payload = b"\xff\x00{ exact spacing }\n"
    client = _client_for(_present(payload, 42))

    batch = read_atomic_redis_sources(client, (KEY_A,))
    result = batch.results[0]

    assert result.exact_payload_bytes is payload
    assert result.payload_sha256 == hashlib.sha256(payload).hexdigest()
    assert result.payload_byte_count == len(payload)
    assert result.pttl_ms == 42
    assert result.redis_type == "string"
    assert result.present is True
    assert payload.hex() not in repr(result)
    assert repr(payload) not in repr(result)


def test_missing_source_has_consistent_none_hash_count_and_pttl() -> None:
    batch = read_atomic_redis_sources(_client_for(_missing()), [KEY_A])
    result = batch.results[0]

    assert result.redis_type == "none"
    assert result.present is False
    assert result.exact_payload_bytes is None
    assert result.payload_sha256 is None
    assert result.payload_byte_count == 0
    assert result.pttl_ms == -2


def test_empty_exact_bytes_are_present_not_missing() -> None:
    result = read_atomic_redis_sources(_client_for(_present(b"", -1)), [KEY_A]).results[0]
    assert result.present is True
    assert result.exact_payload_bytes == b""
    assert result.payload_sha256 == hashlib.sha256(b"").hexdigest()
    assert result.payload_byte_count == 0
    assert result.pttl_ms == -1


def test_server_time_is_canonical_utc_microsecond_observation_clock() -> None:
    batch = read_atomic_redis_sources(_client_for(_present(), time=(0, 7)), [KEY_A])
    assert batch.server_time_seconds == 0
    assert batch.server_time_microseconds == 7
    assert batch.server_observed_at == "1970-01-01T00:00:00.000007Z"
    assert batch.results[0].server_observed_at == batch.server_observed_at


def test_batch_material_and_hash_are_canonical_and_bind_every_result() -> None:
    batch = read_atomic_redis_sources(
        _client_for(_present(b"abc", 10), _missing(), time=(10, 20)),
        [KEY_A, KEY_B],
    )
    material = json.loads(batch.batch_material_json)

    assert batch.batch_material_json == json.dumps(
        material,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    expected_hash = hashlib.sha256(batch.batch_material_json.encode("ascii")).hexdigest()
    assert batch.batch_material_sha256 == expected_hash
    assert batch.batch_id == f"trainer_atomic_redis_source_read_v2_{expected_hash}"
    assert material["results"][0]["payload_sha256"] == hashlib.sha256(b"abc").hexdigest()
    assert material["results"][1]["present"] is False
    assert material["total_payload_byte_count"] == 3
    assert material["downstream_status"] == ATOMIC_REDIS_SOURCE_READ_DOWNSTREAM_STATUS
    assert material["live_execution_authorized"] is False
    assert material["transport_authenticity_attested"] is False
    assert material["server_time_is_consumer_observed_at"] is False
    assert material["redis_payload_read_operation"] == ("GETRANGE_INCLUSIVE_CAP_PLUS_ONE")
    assert material["redis_transaction_command_order_per_key"] == [
        "TYPE",
        "GETRANGE",
        "PTTL",
    ]
    assert material["max_source_payload_bytes"] == MAX_SOURCE_PAYLOAD_BYTES
    assert material["max_range_reply_bytes"] == MAX_RANGE_REPLY_BYTES
    assert material["max_batch_materialized_payload_bytes"] == (
        MAX_BATCH_MATERIALIZED_PAYLOAD_BYTES
    )


def test_equal_complete_responses_are_deterministic_and_order_is_bound() -> None:
    first = read_atomic_redis_sources(
        _client_for(_present(b"a", 8), _present(b"b", 9)),
        [KEY_A, KEY_B],
    )
    second = read_atomic_redis_sources(
        _client_for(_present(b"a", 8), _present(b"b", 9)),
        [KEY_A, KEY_B],
    )
    reversed_batch = read_atomic_redis_sources(
        _client_for(_present(b"b", 9), _present(b"a", 8)),
        [KEY_B, KEY_A],
    )

    assert first == second
    assert first.batch_material_json == second.batch_material_json
    assert first.batch_material_sha256 == second.batch_material_sha256
    assert reversed_batch.batch_material_sha256 != first.batch_material_sha256


def test_results_are_immutable_and_explicitly_nonconsumable() -> None:
    batch = read_atomic_redis_sources(_client_for(_present()), [KEY_A])
    result = batch.results[0]

    assert batch.schema_version == ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION
    assert result.schema_version == ATOMIC_REDIS_SOURCE_RESULT_SCHEMA_VERSION
    assert batch.evidence_classification == ATOMIC_REDIS_SOURCE_READ_EVIDENCE_CLASSIFICATION
    assert batch.downstream_status == ATOMIC_REDIS_SOURCE_READ_DOWNSTREAM_STATUS
    for evidence in (batch, result):
        assert evidence.read_only is True
        assert evidence.paper_provenance_only is True
        assert evidence.live_execution_authorized is False
        assert evidence.source_schema_attested is False
        assert evidence.source_finality_attested is False
        assert evidence.ledger_receipt_emitted is False
        assert evidence.consumer_eligible is False
        assert evidence.transport_authenticity_attested is False
        assert evidence.server_time_is_consumer_observed_at is False
        assert evidence.server_time_clock_semantics == REDIS_TIME_CLOCK_SEMANTICS
    with pytest.raises(FrozenInstanceError):
        result.pttl_ms = 0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        batch.results = ()  # type: ignore[misc]


@pytest.mark.parametrize("keys", [(), [], [KEY_A] * (MAX_SOURCE_KEYS_PER_BATCH + 1)])
def test_key_count_must_be_bounded(keys: object) -> None:
    client = _client_for(_present())
    _assert_fixed_error(
        client,
        keys,
        AtomicRedisSourceReadValidationError,
        "atomic_redis_source_key_count_invalid",
    )
    assert client.transactions == []


def test_mutating_caller_list_cannot_expand_the_bounded_key_snapshot() -> None:
    initial_keys = [f"v2:test:atomic:key:{index}" for index in range(4)]
    requested_keys = list(initial_keys)
    client = _client_for(*(_present(str(index).encode()) for index in range(4)))
    mutation_observed = False

    def mutate_after_snapshot(frame: Any, event: str, _arg: object) -> Any:
        nonlocal mutation_observed
        if (
            event == "line"
            and frame.f_code is reader._validated_source_keys.__code__
            and "snapshot" in frame.f_locals
            and not mutation_observed
        ):
            requested_keys.extend(
                f"v2:test:atomic:late:{index}" for index in range(MAX_SOURCE_KEYS_PER_BATCH * 16)
            )
            mutation_observed = True
        return mutate_after_snapshot

    prior_trace = sys.gettrace()
    sys.settrace(mutate_after_snapshot)
    try:
        batch = read_atomic_redis_sources(client, requested_keys)
    finally:
        sys.settrace(prior_trace)

    assert mutation_observed is True
    assert len(requested_keys) > MAX_SOURCE_KEYS_PER_BATCH
    assert [result.source_key for result in batch.results] == initial_keys
    assert [
        command for command in client.pipeline_instance.commands if command[0] == "GETRANGE"
    ] == [("GETRANGE", key, 0, MAX_SOURCE_PAYLOAD_BYTES) for key in initial_keys]


@pytest.mark.parametrize(
    "keys",
    [
        "v2:not-a-container",
        {KEY_A},
        iter([KEY_A]),
        (candidate for candidate in [KEY_A]),
    ],
)
def test_only_exact_builtin_list_or_tuple_key_containers_are_accepted(keys: object) -> None:
    _assert_fixed_error(
        _client_for(_present()),
        keys,
        AtomicRedisSourceReadValidationError,
        "atomic_redis_source_keys_container_invalid",
    )


@pytest.mark.parametrize(
    "key",
    [
        "legacy:key",
        "V2:market:key",
        "v2:",
        "v2:market key",
        "v2:market:*",
        "v2:market:%",
        "v2:market:\nkey",
        "v2:märkët:key",
        "v2:" + ("a" * (MAX_SOURCE_KEY_BYTES - 2)),
        b"v2:market:key",
        True,
        1,
        None,
    ],
)
def test_invalid_source_keys_fail_before_redis(key: object) -> None:
    client = _client_for(_present())
    _assert_fixed_error(
        client,
        [key],
        AtomicRedisSourceReadValidationError,
        "atomic_redis_source_key_invalid",
    )
    assert client.transactions == []


def test_maximum_length_ascii_v2_key_is_accepted() -> None:
    key = "v2:" + ("a" * (MAX_SOURCE_KEY_BYTES - 3))
    result = read_atomic_redis_sources(_client_for(_present()), [key]).results[0]
    assert len(key) == MAX_SOURCE_KEY_BYTES
    assert result.source_key == key


def test_duplicate_keys_fail_before_redis() -> None:
    client = _client_for(_present(), _present())
    _assert_fixed_error(
        client,
        [KEY_A, KEY_A],
        AtomicRedisSourceReadValidationError,
        "atomic_redis_source_keys_duplicate",
    )
    assert client.transactions == []


@pytest.mark.parametrize(
    "connection_kwargs",
    [
        {"decode_responses": True},
        {},
        {"decode_responses": 0},
        {"decode_responses": None},
        [("decode_responses", False)],
    ],
)
def test_raw_decode_responses_false_client_is_required(connection_kwargs: object) -> None:
    client = _client_for(_present(), connection_kwargs=connection_kwargs)
    _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadValidationError,
        "atomic_redis_client_raw_mode_unverified",
    )
    assert client.transactions == []


def test_mutating_connection_metadata_cannot_change_the_bounded_snapshot() -> None:
    connection_kwargs: dict[str, object] = {
        "decode_responses": False,
        "socket_timeout": 1,
    }
    client = _client_for(_present(), connection_kwargs=connection_kwargs)
    mutation_observed = False

    def mutate_after_snapshot(frame: Any, event: str, _arg: object) -> Any:
        nonlocal mutation_observed
        if (
            event == "line"
            and frame.f_code is reader._verify_raw_client.__code__
            and "metadata_snapshot" in frame.f_locals
            and not mutation_observed
        ):
            del connection_kwargs["decode_responses"]
            connection_kwargs["replacement"] = HOSTILE_DETAIL
            mutation_observed = True
        return mutate_after_snapshot

    prior_trace = sys.gettrace()
    sys.settrace(mutate_after_snapshot)
    try:
        batch = read_atomic_redis_sources(client, [KEY_A])
    finally:
        sys.settrace(prior_trace)

    assert mutation_observed is True
    assert batch.results[0].source_key == KEY_A
    assert connection_kwargs == {
        "socket_timeout": 1,
        "replacement": HOSTILE_DETAIL,
    }


def test_connection_metadata_field_count_is_resource_bounded() -> None:
    connection_kwargs: dict[str, object] = {
        "decode_responses": False,
        **{f"field_{index}": index for index in range(reader.MAX_REDIS_CONNECTION_METADATA_FIELDS)},
    }
    client = _client_for(_present(), connection_kwargs=connection_kwargs)
    _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadValidationError,
        "atomic_redis_client_raw_mode_unverified",
    )
    assert client.transactions == []


@pytest.mark.parametrize("raw_type", ["string", bytearray(b"string"), b"list", None, True])
def test_type_response_must_be_exact_raw_string_or_none_bytes(raw_type: object) -> None:
    client = _FakeClient([raw_type, b"payload", 1, TIME])
    _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadIntegrityError,
        "atomic_redis_source_read_type_invalid",
    )
    assert client.pipeline_instance.reset_calls == 1
    assert client.pipeline_instance.close_calls == 1


@pytest.mark.parametrize("payload", ["decoded", bytearray(b"bytes"), memoryview(b"bytes"), 1, True])
def test_present_payload_must_be_exact_bytes(payload: object) -> None:
    client = _FakeClient([b"string", payload, 1, TIME])
    _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadIntegrityError,
        "atomic_redis_source_read_payload_invalid",
    )


@pytest.mark.parametrize("pttl", [True, False, 1.0, "1", None])
def test_pttl_must_be_exact_int_not_bool_or_convertible(pttl: object) -> None:
    client = _FakeClient([b"string", b"payload", pttl, TIME])
    _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadIntegrityError,
        "atomic_redis_source_read_pttl_invalid",
    )


@pytest.mark.parametrize("pttl", [-3, -2, reader.MAX_REDIS_PTTL_MS + 1])
def test_present_pttl_must_be_persistent_or_nonnegative_redis_range(pttl: int) -> None:
    client = _FakeClient([b"string", b"payload", pttl, TIME])
    _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadIntegrityError,
        "atomic_redis_source_read_present_pttl_inconsistent",
    )


@pytest.mark.parametrize(
    ("payload", "pttl"),
    [
        (b"unexpected", -2),
        (None, -2),
        (None, -1),
        (b"", -1),
        (b"", 0),
        (b"", 1),
    ],
)
def test_missing_type_payload_and_pttl_must_be_consistent(payload: object, pttl: int) -> None:
    client = _FakeClient([b"none", payload, pttl, TIME])
    _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadIntegrityError,
        "atomic_redis_source_read_missing_inconsistent",
    )


@pytest.mark.parametrize(
    "raw_time",
    [
        [1, 2],
        (1,),
        (1, 2, 3),
        (True, 2),
        (1, False),
        (1.0, 2),
        (1, "2"),
        (-1, 0),
        (1, -1),
        (1, 1_000_000),
        (10**100, 0),
    ],
)
def test_redis_time_has_exact_tuple_int_range_and_datetime_contract(raw_time: object) -> None:
    client = _client_for(_present(), time=raw_time)
    _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadIntegrityError,
        "atomic_redis_source_read_time_invalid",
    )


@pytest.mark.parametrize(
    "responses",
    [
        (b"string", b"payload", 1, TIME),
        "not-a-list",
        None,
        {"responses": []},
    ],
)
def test_execute_response_must_be_exact_builtin_list(responses: object) -> None:
    client = _FakeClient(responses)
    _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadIntegrityError,
        "atomic_redis_source_read_response_container_invalid",
    )


@pytest.mark.parametrize(
    "responses",
    [
        [],
        [b"string", b"payload", 1],
        [b"string", b"payload", 1, TIME, b"extra"],
    ],
)
def test_response_arity_is_exact_for_requested_key_count(responses: list[object]) -> None:
    client = _FakeClient(responses)
    _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadIntegrityError,
        "atomic_redis_source_read_response_arity_invalid",
    )


def test_per_payload_byte_limit_is_enforced_without_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reader, "MAX_SOURCE_PAYLOAD_BYTES", 3)
    accepted = read_atomic_redis_sources(_client_for(_present(b"abc")), [KEY_A])
    assert accepted.total_payload_byte_count == 3
    client = _client_for(_present(b"abcd"))
    _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadIntegrityError,
        "atomic_redis_source_read_payload_bytes_exceeded",
    )


def test_exact_payload_cap_is_accepted_and_cap_plus_one_is_rejected() -> None:
    exact_cap = b"x" * MAX_SOURCE_PAYLOAD_BYTES
    accepted = read_atomic_redis_sources(_client_for(_present(exact_cap)), [KEY_A])
    assert accepted.results[0].exact_payload_bytes == exact_cap

    _assert_fixed_error(
        _client_for(_present(exact_cap + b"!")),
        [KEY_A],
        AtomicRedisSourceReadIntegrityError,
        "atomic_redis_source_read_payload_bytes_exceeded",
    )


def test_reply_larger_than_requested_cap_plus_one_is_an_integrity_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reader, "MAX_SOURCE_PAYLOAD_BYTES", 3)
    monkeypatch.setattr(reader, "MAX_RANGE_REPLY_BYTES", 4)
    _assert_fixed_error(
        _client_for(_present(b"12345")),
        [KEY_A],
        AtomicRedisSourceReadIntegrityError,
        "atomic_redis_source_read_range_reply_bytes_invalid",
    )


def test_accepted_batch_capacity_product_cannot_exceed_aggregate_limit() -> None:
    assert MAX_SOURCE_PAYLOAD_BYTES * MAX_SOURCE_KEYS_PER_BATCH <= (
        reader.MAX_AGGREGATE_PAYLOAD_BYTES
    )
    assert MAX_RANGE_REPLY_BYTES == MAX_SOURCE_PAYLOAD_BYTES + 1
    assert MAX_BATCH_MATERIALIZED_PAYLOAD_BYTES == (
        reader.MAX_AGGREGATE_PAYLOAD_BYTES + MAX_SOURCE_KEYS_PER_BATCH
    )


def test_aggregate_payload_byte_limit_is_enforced_in_requested_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reader, "MAX_SOURCE_PAYLOAD_BYTES", 10)
    monkeypatch.setattr(reader, "MAX_AGGREGATE_PAYLOAD_BYTES", 3)
    client = _client_for(_present(b"ab"), _present(b"cd"))
    _assert_fixed_error(
        client,
        [KEY_A, KEY_B],
        AtomicRedisSourceReadIntegrityError,
        "atomic_redis_source_read_aggregate_bytes_exceeded",
    )


@pytest.mark.parametrize("failure", ["TYPE", "GETRANGE", "PTTL", "TIME"])
def test_pipeline_is_reset_and_closed_when_command_queueing_fails(failure: str) -> None:
    client = _client_for(_present(), command_failure=failure)
    _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadTransportError,
        "atomic_redis_source_read_transport_failed",
    )
    assert client.pipeline_instance.reset_calls == 1
    assert client.pipeline_instance.close_calls == 1


def test_pipeline_is_reset_and_closed_when_execute_fails() -> None:
    client = _client_for(_present(), execute_failure=True)
    _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadTransportError,
        "atomic_redis_source_read_transport_failed",
    )
    assert client.pipeline_instance.reset_calls == 1
    assert client.pipeline_instance.close_calls == 1


def test_exact_response_list_is_detached_before_pipeline_cleanup() -> None:
    client = _client_for(_present(b"stable"), clear_responses_on_reset=True)
    batch = read_atomic_redis_sources(client, [KEY_A])

    assert client.pipeline_instance.responses == []
    assert batch.results[0].exact_payload_bytes == b"stable"


def test_pipeline_creation_failure_has_fixed_secret_free_transport_reason() -> None:
    client = _client_for(_present(), pipeline_failure=True)
    error = _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadTransportError,
        "atomic_redis_source_read_transport_failed",
    )
    assert error.__context__ is None
    assert error.__cause__ is None


def test_cleanup_failure_after_success_fails_closed_with_fixed_reason() -> None:
    client = _client_for(
        _present(),
        cleanup_failures=frozenset({"reset", "close"}),
    )
    error = _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadTransportError,
        "atomic_redis_source_read_pipeline_cleanup_failed",
    )
    assert client.pipeline_instance.reset_calls == 1
    assert client.pipeline_instance.close_calls == 1
    assert error.__context__ is None
    assert error.__cause__ is None


@pytest.mark.parametrize("failed_method", ["reset", "close"])
def test_each_supported_cleanup_method_is_independently_required(failed_method: str) -> None:
    client = _client_for(
        _present(),
        cleanup_failures=frozenset({failed_method}),
    )
    _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadTransportError,
        "atomic_redis_source_read_pipeline_cleanup_failed",
    )
    assert client.pipeline_instance.reset_calls == 1
    assert client.pipeline_instance.close_calls == 1


def test_primary_transport_failure_remains_fixed_when_cleanup_also_fails() -> None:
    client = _client_for(
        _present(),
        execute_failure=True,
        cleanup_failures=frozenset({"reset", "close"}),
    )
    _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadTransportError,
        "atomic_redis_source_read_transport_failed",
    )
    assert client.pipeline_instance.reset_calls == 1
    assert client.pipeline_instance.close_calls == 1


class _HookBomb:
    calls = 0

    @property  # type: ignore[misc]  # deliberately hostile runtime fixture
    def __class__(self) -> type[object]:  # type: ignore[override]
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __bool__(self) -> bool:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __str__(self) -> str:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __len__(self) -> int:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __int__(self) -> int:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __index__(self) -> int:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)


class _HostileString(str):
    calls = 0

    @property  # type: ignore[misc]  # deliberately hostile runtime fixture
    def __class__(self) -> type[object]:  # type: ignore[override]
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __str__(self) -> str:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __len__(self) -> int:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __bool__(self) -> bool:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def strip(self, chars: str | None = None) -> str:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)


class _HostileList(list[object]):
    calls = 0

    @property  # type: ignore[misc]  # deliberately hostile runtime fixture
    def __class__(self) -> type[object]:  # type: ignore[override]
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __len__(self) -> int:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __iter__(self):  # type: ignore[no-untyped-def]
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)


class _HostileInt(int):
    calls = 0

    @property  # type: ignore[misc]  # deliberately hostile runtime fixture
    def __class__(self) -> type[object]:  # type: ignore[override]
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __int__(self) -> int:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __index__(self) -> int:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __str__(self) -> str:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)


class _HostileBytes(bytes):
    calls = 0

    @property  # type: ignore[misc]  # deliberately hostile runtime fixture
    def __class__(self) -> type[object]:  # type: ignore[override]
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __len__(self) -> int:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __bytes__(self) -> bytes:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __str__(self) -> str:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)


class _HostileTuple(tuple[object, ...]):
    calls = 0

    @property  # type: ignore[misc]  # deliberately hostile runtime fixture
    def __class__(self) -> type[object]:  # type: ignore[override]
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __len__(self) -> int:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __iter__(self):  # type: ignore[no-untyped-def]
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)


class _HostileDict(dict[str, object]):
    calls = 0

    @property  # type: ignore[misc]  # deliberately hostile runtime fixture
    def __class__(self) -> type[object]:  # type: ignore[override]
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __len__(self) -> int:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __iter__(self):  # type: ignore[no-untyped-def]
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)

    def __bool__(self) -> bool:
        type(self).calls += 1
        raise RuntimeError(HOSTILE_DETAIL)


@pytest.mark.parametrize("case", ["container", "string", "object"])
def test_hostile_key_containers_and_values_run_no_caller_hooks(case: str) -> None:
    cases: dict[str, tuple[object, str, type[Any]]] = {
        "container": (
            _HostileList([KEY_A]),
            "atomic_redis_source_keys_container_invalid",
            _HostileList,
        ),
        "string": (
            [_HostileString(KEY_A)],
            "atomic_redis_source_key_invalid",
            _HostileString,
        ),
        "object": ([_HookBomb()], "atomic_redis_source_key_invalid", _HookBomb),
    }
    keys, reason, counter = cases[case]
    counter.calls = 0
    _assert_fixed_error(
        _client_for(_present()),
        keys,
        AtomicRedisSourceReadValidationError,
        reason,
    )
    assert counter.calls == 0


@pytest.mark.parametrize(
    "case",
    [
        "container",
        "type",
        "type_bytes",
        "payload",
        "payload_bytes",
        "pttl_object",
        "pttl_int",
        "time_container",
        "time_int",
    ],
)
def test_hostile_response_values_run_no_class_bool_len_string_or_conversion_hooks(
    case: str,
) -> None:
    cases: dict[str, tuple[object, str, type[Any]]] = {
        "container": (
            _HostileList([b"string", b"payload", 1, TIME]),
            "atomic_redis_source_read_response_container_invalid",
            _HostileList,
        ),
        "type": (
            [_HookBomb(), b"payload", 1, TIME],
            "atomic_redis_source_read_type_invalid",
            _HookBomb,
        ),
        "type_bytes": (
            [_HostileBytes(b"string"), b"payload", 1, TIME],
            "atomic_redis_source_read_type_invalid",
            _HostileBytes,
        ),
        "payload": (
            [b"string", _HookBomb(), 1, TIME],
            "atomic_redis_source_read_payload_invalid",
            _HookBomb,
        ),
        "payload_bytes": (
            [b"string", _HostileBytes(b"payload"), 1, TIME],
            "atomic_redis_source_read_payload_invalid",
            _HostileBytes,
        ),
        "pttl_object": (
            [b"string", b"payload", _HookBomb(), TIME],
            "atomic_redis_source_read_pttl_invalid",
            _HookBomb,
        ),
        "pttl_int": (
            [b"string", b"payload", _HostileInt(1), TIME],
            "atomic_redis_source_read_pttl_invalid",
            _HostileInt,
        ),
        "time_container": (
            [b"string", b"payload", 1, _HostileTuple((1, 2))],
            "atomic_redis_source_read_time_invalid",
            _HostileTuple,
        ),
        "time_int": (
            [b"string", b"payload", 1, (_HostileInt(1), 2)],
            "atomic_redis_source_read_time_invalid",
            _HostileInt,
        ),
    }
    responses, reason, counter = cases[case]
    counter.calls = 0
    _assert_fixed_error(
        _FakeClient(responses),
        [KEY_A],
        AtomicRedisSourceReadIntegrityError,
        reason,
    )
    assert counter.calls == 0


def test_hostile_decode_responses_value_runs_no_bool_or_conversion_hooks() -> None:
    hostile = _HookBomb()
    _HookBomb.calls = 0
    client = _client_for(_present(), connection_kwargs={"decode_responses": hostile})
    _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadValidationError,
        "atomic_redis_client_raw_mode_unverified",
    )
    assert _HookBomb.calls == 0


def test_hostile_connection_kwargs_container_runs_no_mapping_hooks() -> None:
    connection_kwargs = _HostileDict(decode_responses=False)
    _HostileDict.calls = 0
    client = _client_for(_present(), connection_kwargs=connection_kwargs)
    _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadValidationError,
        "atomic_redis_client_raw_mode_unverified",
    )
    assert _HostileDict.calls == 0


def test_hostile_connection_kwargs_key_runs_no_string_or_class_hooks() -> None:
    hostile_key = _HostileString("decode_responses")
    _HostileString.calls = 0
    client = _client_for(_present(), connection_kwargs={hostile_key: False})
    _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadValidationError,
        "atomic_redis_client_raw_mode_unverified",
    )
    assert _HostileString.calls == 0


def test_connection_metadata_failure_is_totalized_before_pipeline_creation() -> None:
    class _MetadataFailureClient(_FakeClient):
        def get_connection_kwargs(self) -> dict[str, Any]:
            raise RuntimeError(HOSTILE_DETAIL)

    client = _MetadataFailureClient([b"string", b"payload", 1, TIME])
    error = _assert_fixed_error(
        client,
        [KEY_A],
        AtomicRedisSourceReadValidationError,
        "atomic_redis_client_raw_mode_unverified",
    )
    assert client.transactions == []
    assert error.__context__ is None
    assert error.__cause__ is None


def test_module_is_unwired_and_contains_no_redis_write_calls() -> None:
    source = inspect.getsource(reader)
    tree = ast.parse(source)
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_from = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "redis" not in imported_modules
    assert "client's post-response ``consumer_observed_at``" in (reader.__doc__ or "")
    assert "Python-constructible immutable value carriers" in (reader.__doc__ or "")
    assert "cannot force its full body" in (reader.__doc__ or "")
    assert not any("exact_source_read_capture" in module for module in imported_from)
    assert not any("durable_feature_snapshot_ledger" in module for module in imported_from)
    assert called_attributes.isdisjoint(
        {
            "append_event",
            "delete",
            "expire",
            "hset",
            "incr",
            "lpush",
            "publish",
            "rpush",
            "set",
            "setex",
            "xadd",
            "zadd",
        }
    )
