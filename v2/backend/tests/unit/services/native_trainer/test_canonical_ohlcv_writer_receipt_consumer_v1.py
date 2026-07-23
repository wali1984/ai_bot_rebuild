from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import redis

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
)
from v2.backend.app.services.market_state_integrity.closed_window_redis_store import (
    atomic_merge_closed_window,
)
from v2.backend.app.services.native_trainer import (
    canonical_ohlcv_writer_receipt_consumer_v1 as consumer_module,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_writer_receipt_consumer_v1 import (
    BINANCE_REST_WRITER_ROLE,
    BINANCE_WSS_WRITER_ROLE,
    EXISTING_PAYLOAD_ADOPTER_ROLE,
    CanonicalOhlcvWriterReceiptConsumerError,
    CanonicalOhlcvWriterReceiptConsumerIntegrityError,
    CanonicalOhlcvWriterReceiptConsumerTransportError,
    CanonicalOhlcvWriterReceiptConsumerValidationError,
    consume_current_canonical_ohlcv_writer_receipt,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
)

SYMBOL = "BTCUSDT"
TIMEFRAME = "4h"
CANONICAL_KEY = "v2:market:ohlcv_closed:binance:BTCUSDT:4h"
POINTER_KEY = (
    "v2:market:ohlcv_closed:publication_receipt:latest:binance:BTCUSDT:4h"
)
WSS_CODE_SHA256 = "1" * 64
REST_CODE_SHA256 = "2" * 64
CONFIG_A_SHA256 = "3" * 64
CONFIG_B_SHA256 = "4" * 64
MUTABLE_TTL_SECONDS = 86_400
RECEIPT_TTL_SECONDS = 43_200
ARCHIVE_TTL_SECONDS = 57_600


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256_material(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _allowlist() -> dict[str, tuple[str, ...]]:
    return {
        BINANCE_WSS_WRITER_ROLE: (WSS_CODE_SHA256,),
        BINANCE_REST_WRITER_ROLE: (REST_CODE_SHA256,),
    }


def _current_row(*, latest_interval_offset: int = 0) -> dict[str, Any]:
    duration_ms = TIMEFRAME_DURATION_MS[TIMEFRAME]
    now_ms = int(time.time() * 1000)
    latest_close = (
        (now_ms // duration_ms) * duration_ms
        - 1
        - latest_interval_offset * duration_ms
    )
    open_time = latest_close - duration_ms + 1
    source = [
        open_time,
        "100.0",
        "103.0",
        "99.0",
        "102.0",
        "12.0",
        latest_close,
        "1224.0",
        10,
        "6.0",
        "612.0",
        "0",
    ]
    return canonical_from_binance_rest(
        source,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        ingested_at=latest_close + 1,
    ).to_dict()


@pytest.fixture(scope="module")
def redis_socket(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    executable = shutil.which("redis-server")
    if executable is None:
        pytest.skip("redis-server is required for the real publication tests")
    root = tmp_path_factory.mktemp("writer-receipt-consumer-redis")
    socket_path = str(root / "redis.sock")
    process = subprocess.Popen(  # noqa: S603 - fixed local executable/arguments
        [
            executable,
            "--port",
            "0",
            "--save",
            "",
            "--appendonly",
            "no",
            "--unixsocket",
            socket_path,
            "--unixsocketperm",
            "700",
            "--dir",
            str(root),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            probe = redis.Redis(
                unix_socket_path=socket_path,
                decode_responses=False,
            )
            if probe.ping():
                break
        except (OSError, redis.RedisError):
            time.sleep(0.02)
    else:
        process.terminate()
        process.wait(timeout=5)
        pytest.fail("ephemeral redis-server did not become ready")
    try:
        yield socket_path
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.fixture()
def raw_client(redis_socket: str) -> redis.Redis:
    client = redis.Redis(
        unix_socket_path=redis_socket,
        decode_responses=False,
    )
    client.flushdb()
    return client


def _publish(
    client: redis.Redis,
    *,
    producer_role: str = BINANCE_WSS_WRITER_ROLE,
    producer_code_sha256: str = WSS_CODE_SHA256,
    producer_config_sha256: str = CONFIG_A_SHA256,
) -> Any:
    return atomic_merge_closed_window(
        client,
        redis_key=CANONICAL_KEY,
        new_rows=(_current_row(),),
        producer_role=producer_role,
        producer_code_sha256=producer_code_sha256,
        producer_config_sha256=producer_config_sha256,
        receipt_ttl_seconds=RECEIPT_TTL_SECONDS,
        archive_ttl_seconds=ARCHIVE_TTL_SECONDS,
        ttl_policy="set",
        ttl_seconds=MUTABLE_TTL_SECONDS,
    )


def _consume(
    client: Any,
    tmp_path: Path,
    *,
    allowlist: Mapping[str, object] | None = None,
    max_attempts: int = 4,
) -> tuple[Any, ImmutableSourcePayloadStore]:
    store = ImmutableSourcePayloadStore(tmp_path / "source-payloads")
    capture = consume_current_canonical_ohlcv_writer_receipt(
        client,
        store,
        expected_symbol=SYMBOL,
        expected_timeframe=TIMEFRAME,
        trusted_writer_code_sha256_by_role=(
            _allowlist() if allowlist is None else allowlist
        ),
        max_attempts=max_attempts,
    )
    return capture, store


def _rewrite_receipt(
    client: redis.Redis,
    receipt_key: str,
    mutate: Callable[[dict[str, Any]], None],
    *,
    rehash: bool,
) -> dict[str, Any]:
    raw = client.get(receipt_key)
    assert isinstance(raw, bytes)
    receipt = json.loads(raw)
    mutate(receipt)
    if rehash:
        unsigned = dict(receipt)
        unsigned.pop("receipt_sha256", None)
        receipt["receipt_sha256"] = _sha256_material(unsigned)
    pttl_ms = client.pttl(receipt_key)
    assert pttl_ms > 0
    assert client.set(receipt_key, _canonical_json_bytes(receipt), px=pttl_ms)
    return receipt


class _PipelineProxy:
    def __init__(
        self,
        inner: Any,
        *,
        call_number: int,
        before_execute: Callable[[int], None] | None,
        time_override: tuple[int, int] | None,
    ) -> None:
        self._inner = inner
        self._call_number = call_number
        self._before_execute = before_execute
        self._time_override = time_override

    def type(self, key: str) -> _PipelineProxy:
        self._inner.type(key)
        return self

    def getrange(self, key: str, start: int, end: int) -> _PipelineProxy:
        self._inner.getrange(key, start, end)
        return self

    def pttl(self, key: str) -> _PipelineProxy:
        self._inner.pttl(key)
        return self

    def time(self) -> _PipelineProxy:
        self._inner.time()
        return self

    def execute(self) -> list[object]:
        if self._before_execute is not None:
            self._before_execute(self._call_number)
        response = list(self._inner.execute())
        if self._time_override is not None:
            response[-1] = self._time_override
        return response

    def reset(self) -> None:
        self._inner.reset()

    def close(self) -> None:
        self._inner.close()


class _ClientProxy:
    def __init__(
        self,
        client: redis.Redis,
        *,
        before_execute: Callable[[int], None] | None = None,
        time_overrides: Mapping[int, tuple[int, int]] | None = None,
    ) -> None:
        self._client = client
        self._before_execute = before_execute
        self._time_overrides = dict(time_overrides or {})
        self.pipeline_calls = 0

    def get_connection_kwargs(self) -> dict[str, Any]:
        return dict(self._client.get_connection_kwargs())

    def pipeline(self, *, transaction: bool) -> _PipelineProxy:
        self.pipeline_calls += 1
        return _PipelineProxy(
            self._client.pipeline(transaction=transaction),
            call_number=self.pipeline_calls,
            before_execute=self._before_execute,
            time_override=self._time_overrides.get(self.pipeline_calls),
        )


class _BrokenPipeline:
    def type(self, _key: str) -> _BrokenPipeline:
        return self

    def getrange(self, _key: str, _start: int, _end: int) -> _BrokenPipeline:
        return self

    def pttl(self, _key: str) -> _BrokenPipeline:
        return self

    def time(self) -> _BrokenPipeline:
        return self

    def execute(self) -> list[object]:
        raise RuntimeError("hostile transport detail")

    def reset(self) -> None:
        return None

    def close(self) -> None:
        return None


class _BrokenClient:
    def get_connection_kwargs(self) -> dict[str, Any]:
        return {"decode_responses": False}

    def pipeline(self, *, transaction: bool) -> _BrokenPipeline:
        assert transaction is True
        return _BrokenPipeline()


@pytest.mark.parametrize(
    ("producer_role", "producer_code_sha256"),
    [
        (BINANCE_WSS_WRITER_ROLE, WSS_CODE_SHA256),
        (BINANCE_REST_WRITER_ROLE, REST_CODE_SHA256),
    ],
)
def test_genuine_writer_receipt_is_independently_rederived_and_cas_captured(
    raw_client: redis.Redis,
    tmp_path: Path,
    producer_role: str,
    producer_code_sha256: str,
) -> None:
    publication = _publish(
        raw_client,
        producer_role=producer_role,
        producer_code_sha256=producer_code_sha256,
    )

    capture, store = _consume(raw_client, tmp_path)

    receipt = capture.writer_receipt
    assert len(consumer_module._WRITER_RECEIPT_FIELDS) == 39
    assert set(receipt) == set(consumer_module._WRITER_RECEIPT_FIELDS)
    assert capture.revision_id == publication.revision_id
    assert capture.producer_role == producer_role
    assert capture.producer_code_sha256 == producer_code_sha256
    assert capture.exact_canonical_payload_bytes == raw_client.get(CANONICAL_KEY)
    assert capture.exact_canonical_payload_bytes == raw_client.get(capture.archive_key)
    assert capture.exact_writer_receipt_bytes == raw_client.get(capture.receipt_key)
    assert store.get(
        capture.canonical_payload_address.payload_sha256,
        expected_byte_count=capture.exact_payload_byte_count,
    ) == capture.exact_canonical_payload_bytes
    assert store.get(
        capture.receipt_payload_address.payload_sha256,
        expected_byte_count=capture.receipt_payload_address.payload_byte_count,
    ) == capture.exact_writer_receipt_bytes
    assert store.get(
        capture.pointer_payload_address.payload_sha256,
        expected_byte_count=capture.pointer_payload_address.payload_byte_count,
    ) == capture.revision_id.encode("ascii")
    manifest = capture.tuple_manifest
    assert [row["source_key"] for row in manifest["ordered_atomic_source_results"]] == [
        CANONICAL_KEY,
        capture.archive_key,
        capture.receipt_key,
        POINTER_KEY,
    ]
    assert manifest["canonical_archive_exact_match"] is True
    assert manifest["writer_publication_receipt_verified"] is True


def test_every_consumer_and_writer_authority_field_is_false(
    raw_client: redis.Redis,
    tmp_path: Path,
) -> None:
    _publish(raw_client)
    capture, _store = _consume(raw_client, tmp_path)

    assert all(
        getattr(capture, field_name) is False
        for field_name in consumer_module._CONSUMER_AUTHORITY_FIELDS
    )
    assert all(
        capture.tuple_manifest[field_name] is False
        for field_name in consumer_module._CONSUMER_AUTHORITY_FIELDS
    )
    assert all(
        capture.writer_receipt[field_name] is False
        for field_name in consumer_module._WRITER_AUTHORITY_FIELDS
    )


@pytest.mark.parametrize(
    "bad_allowlist",
    [
        {BINANCE_WSS_WRITER_ROLE: (WSS_CODE_SHA256,)},
        {
            BINANCE_WSS_WRITER_ROLE: (WSS_CODE_SHA256,),
            BINANCE_REST_WRITER_ROLE: (REST_CODE_SHA256,),
            EXISTING_PAYLOAD_ADOPTER_ROLE: ("5" * 64,),
        },
        {
            BINANCE_WSS_WRITER_ROLE: ("not-a-sha256",),
            BINANCE_REST_WRITER_ROLE: (REST_CODE_SHA256,),
        },
        {
            BINANCE_WSS_WRITER_ROLE: (WSS_CODE_SHA256,),
            BINANCE_REST_WRITER_ROLE: (WSS_CODE_SHA256,),
        },
    ],
)
def test_allowlist_shape_hashes_and_cross_role_collisions_fail_closed(
    raw_client: redis.Redis,
    tmp_path: Path,
    bad_allowlist: Mapping[str, object],
) -> None:
    _publish(raw_client)

    with pytest.raises(CanonicalOhlcvWriterReceiptConsumerValidationError):
        _consume(raw_client, tmp_path, allowlist=bad_allowlist)


@pytest.mark.parametrize(
    ("producer_role", "producer_code_sha256", "expected_reason"),
    [
        (
            EXISTING_PAYLOAD_ADOPTER_ROLE,
            "5" * 64,
            "adopter_receipt_not_trusted",
        ),
        (
            "UNRECOGNIZED_CANONICAL_WINDOW_WRITER_V1",
            "6" * 64,
            "writer_role_not_trusted",
        ),
        (
            BINANCE_WSS_WRITER_ROLE,
            REST_CODE_SHA256,
            "writer_code_not_allowlisted_for_role",
        ),
    ],
)
def test_adopter_unknown_and_cross_role_receipts_are_rejected(
    raw_client: redis.Redis,
    tmp_path: Path,
    producer_role: str,
    producer_code_sha256: str,
    expected_reason: str,
) -> None:
    _publish(
        raw_client,
        producer_role=producer_role,
        producer_code_sha256=producer_code_sha256,
    )

    with pytest.raises(
        CanonicalOhlcvWriterReceiptConsumerIntegrityError,
        match=expected_reason,
    ):
        _consume(raw_client, tmp_path)


@pytest.mark.parametrize(
    ("target", "wrong_type"),
    [
        ("canonical", False),
        ("archive", False),
        ("receipt", False),
        ("pointer", False),
        ("archive", True),
    ],
)
def test_missing_or_wrong_type_publication_member_fails_closed(
    raw_client: redis.Redis,
    tmp_path: Path,
    target: str,
    wrong_type: bool,
) -> None:
    publication = _publish(raw_client)
    keys = {
        "canonical": CANONICAL_KEY,
        "archive": publication.archive_key,
        "receipt": publication.receipt_key,
        "pointer": POINTER_KEY,
    }
    key = keys[target]
    raw_client.delete(key)
    if wrong_type:
        raw_client.rpush(key, b"wrong-type")
        raw_client.expire(key, RECEIPT_TTL_SECONDS)

    # A Redis wrong-type command error is deliberately totalized as a
    # transport failure by the shared atomic reader; absent string members
    # fail at the consumer integrity boundary. Both outcomes remain closed.
    expected_error = (
        CanonicalOhlcvWriterReceiptConsumerError
        if wrong_type
        else CanonicalOhlcvWriterReceiptConsumerIntegrityError
    )
    with pytest.raises(expected_error):
        _consume(raw_client, tmp_path, max_attempts=1)


def test_pointer_change_between_discovery_and_authoritative_read_retries(
    raw_client: redis.Redis,
    tmp_path: Path,
) -> None:
    first = _publish(raw_client, producer_config_sha256=CONFIG_A_SHA256)
    second = _publish(raw_client, producer_config_sha256=CONFIG_B_SHA256)
    assert first.revision_id != second.revision_id

    def before_execute(call_number: int) -> None:
        if call_number == 2:
            assert raw_client.set(
                POINTER_KEY,
                first.revision_id.encode("ascii"),
                ex=RECEIPT_TTL_SECONDS,
            )

    proxy = _ClientProxy(raw_client, before_execute=before_execute)
    capture, _store = _consume(proxy, tmp_path)

    assert proxy.pipeline_calls == 4
    assert capture.revision_id == first.revision_id


def test_persistent_pointer_race_exhausts_bounded_retries(
    raw_client: redis.Redis,
    tmp_path: Path,
) -> None:
    first = _publish(raw_client, producer_config_sha256=CONFIG_A_SHA256)
    second = _publish(raw_client, producer_config_sha256=CONFIG_B_SHA256)

    def before_execute(call_number: int) -> None:
        if call_number % 2 == 0:
            discovered_first = (call_number // 2) % 2 == 0
            revision = second.revision_id if discovered_first else first.revision_id
            assert raw_client.set(
                POINTER_KEY,
                revision.encode("ascii"),
                ex=RECEIPT_TTL_SECONDS,
            )

    proxy = _ClientProxy(raw_client, before_execute=before_execute)
    with pytest.raises(
        CanonicalOhlcvWriterReceiptConsumerIntegrityError,
        match="pointer_race_retry_exhausted",
    ):
        _consume(proxy, tmp_path, max_attempts=4)
    assert proxy.pipeline_calls == 8


def test_prepare_window_race_retries_then_reopens_exact_tuple(
    raw_client: redis.Redis,
    tmp_path: Path,
) -> None:
    publication = _publish(raw_client)
    original = raw_client.get(CANONICAL_KEY)
    assert isinstance(original, bytes)
    prepared = _canonical_json_bytes([_current_row(latest_interval_offset=1), _current_row()])

    def before_execute(call_number: int) -> None:
        if call_number == 2:
            assert raw_client.set(CANONICAL_KEY, prepared, ex=MUTABLE_TTL_SECONDS)
        elif call_number == 3:
            assert raw_client.set(CANONICAL_KEY, original, ex=MUTABLE_TTL_SECONDS)

    proxy = _ClientProxy(raw_client, before_execute=before_execute)
    capture, _store = _consume(proxy, tmp_path)

    assert proxy.pipeline_calls == 4
    assert capture.revision_id == publication.revision_id
    assert capture.exact_canonical_payload_bytes == original


@pytest.mark.parametrize(
    "mutation",
    ["missing_field", "authority_true", "receipt_sha", "noncanonical"],
)
def test_writer_receipt_field_authority_hash_and_encoding_tamper_fails_closed(
    raw_client: redis.Redis,
    tmp_path: Path,
    mutation: str,
) -> None:
    publication = _publish(raw_client)
    if mutation == "missing_field":
        _rewrite_receipt(
            raw_client,
            publication.receipt_key,
            lambda value: value.pop("max_ingested_at"),
            rehash=False,
        )
    elif mutation == "authority_true":
        _rewrite_receipt(
            raw_client,
            publication.receipt_key,
            lambda value: value.__setitem__("trainer_admission_authorized", True),
            rehash=True,
        )
    elif mutation == "receipt_sha":
        _rewrite_receipt(
            raw_client,
            publication.receipt_key,
            lambda value: value.__setitem__("receipt_sha256", "f" * 64),
            rehash=False,
        )
    else:
        raw = raw_client.get(publication.receipt_key)
        assert isinstance(raw, bytes)
        parsed = json.loads(raw)
        pttl_ms = raw_client.pttl(publication.receipt_key)
        assert raw_client.set(
            publication.receipt_key,
            json.dumps(parsed, indent=2, sort_keys=True).encode("ascii"),
            px=pttl_ms,
        )

    with pytest.raises(CanonicalOhlcvWriterReceiptConsumerIntegrityError):
        _consume(raw_client, tmp_path)


def test_revision_is_rederived_instead_of_trusting_pointer_and_receipt(
    raw_client: redis.Redis,
    tmp_path: Path,
) -> None:
    publication = _publish(raw_client)
    fake_revision = f"v2_ohlcv_closed_{'f' * 64}"
    fake_archive = (
        "v2:market:ohlcv_closed:archive:binance:BTCUSDT:4h:"
        f"{fake_revision}"
    )
    fake_receipt_key = (
        "v2:market:ohlcv_closed:publication_receipt:"
        f"{fake_revision}"
    )
    canonical = raw_client.get(CANONICAL_KEY)
    receipt_raw = raw_client.get(publication.receipt_key)
    assert isinstance(canonical, bytes)
    assert isinstance(receipt_raw, bytes)
    receipt = json.loads(receipt_raw)
    receipt.update(
        {
            "revision_id": fake_revision,
            "archive_key": fake_archive,
            "receipt_key": fake_receipt_key,
        }
    )
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256")
    receipt["receipt_sha256"] = _sha256_material(unsigned)
    assert raw_client.set(fake_archive, canonical, ex=ARCHIVE_TTL_SECONDS)
    assert raw_client.set(
        fake_receipt_key,
        _canonical_json_bytes(receipt),
        ex=RECEIPT_TTL_SECONDS,
    )
    assert raw_client.set(
        POINTER_KEY,
        fake_revision.encode("ascii"),
        ex=RECEIPT_TTL_SECONDS,
    )

    with pytest.raises(
        CanonicalOhlcvWriterReceiptConsumerIntegrityError,
        match="revision_rederivation_mismatch",
    ):
        _consume(raw_client, tmp_path)


@pytest.mark.parametrize("ttl_tamper", ["runtime_order", "declared_cadence"])
def test_runtime_and_declared_ttl_tamper_fails_closed(
    raw_client: redis.Redis,
    tmp_path: Path,
    ttl_tamper: str,
) -> None:
    publication = _publish(raw_client)
    if ttl_tamper == "runtime_order":
        assert raw_client.pexpire(publication.archive_key, 10_000)
    else:
        _rewrite_receipt(
            raw_client,
            publication.receipt_key,
            lambda value: value.__setitem__(
                "receipt_ttl_seconds",
                RECEIPT_TTL_SECONDS + 1,
            ),
            rehash=True,
        )

    with pytest.raises(CanonicalOhlcvWriterReceiptConsumerIntegrityError):
        _consume(raw_client, tmp_path)


def test_future_writer_publication_clock_fails_closed(
    raw_client: redis.Redis,
    tmp_path: Path,
) -> None:
    publication = _publish(raw_client)
    _rewrite_receipt(
        raw_client,
        publication.receipt_key,
        lambda value: value.__setitem__(
            "publication_available_at",
            "2099-01-01T00:00:00.000000Z",
        ),
        rehash=True,
    )

    with pytest.raises(
        CanonicalOhlcvWriterReceiptConsumerValidationError,
        match="clock_order_invalid",
    ):
        _consume(raw_client, tmp_path)


@pytest.mark.parametrize("source_tamper", ["unfinished", "stale", "future_available"])
def test_source_finality_freshness_and_availability_tamper_fails_closed(
    raw_client: redis.Redis,
    tmp_path: Path,
    source_tamper: str,
) -> None:
    publication = _publish(raw_client)
    if source_tamper == "stale":
        rows = [_current_row(latest_interval_offset=1)]
    else:
        rows = [_current_row()]
        if source_tamper == "unfinished":
            rows[-1]["is_closed"] = False
        else:
            future_ms = int(time.time() * 1000) + 60_000
            rows[-1]["ingested_at"] = future_ms
            rows[-1]["available_at"] = future_ms
    tampered = _canonical_json_bytes(rows)
    assert raw_client.set(CANONICAL_KEY, tampered, ex=MUTABLE_TTL_SECONDS)
    assert raw_client.set(
        publication.archive_key,
        tampered,
        ex=ARCHIVE_TTL_SECONDS,
    )

    with pytest.raises(CanonicalOhlcvWriterReceiptConsumerValidationError):
        _consume(raw_client, tmp_path)


def test_transport_failure_is_totalized_without_detail(tmp_path: Path) -> None:
    with pytest.raises(
        CanonicalOhlcvWriterReceiptConsumerTransportError,
        match="atomic_read_transport_failed",
    ) as exc_info:
        _consume(_BrokenClient(), tmp_path)
    assert "hostile transport detail" not in str(exc_info.value)


def test_decode_responses_client_fails_raw_mode_validation(
    redis_socket: str,
    tmp_path: Path,
) -> None:
    decoded_client = redis.Redis(
        unix_socket_path=redis_socket,
        decode_responses=True,
    )

    with pytest.raises(
        CanonicalOhlcvWriterReceiptConsumerValidationError,
        match="atomic_read_validation_failed",
    ):
        _consume(decoded_client, tmp_path)


def test_post_return_cas_corruption_is_detected_on_fresh_access(
    raw_client: redis.Redis,
    tmp_path: Path,
) -> None:
    _publish(raw_client)
    capture, store = _consume(raw_client, tmp_path)
    path = store.path_for(capture.receipt_payload_address.payload_sha256)
    original = capture.exact_writer_receipt_bytes
    corrupted = bytes([original[0] ^ 1]) + original[1:]
    os.chmod(path, 0o600)
    path.write_bytes(corrupted)
    os.chmod(path, 0o400)

    with pytest.raises(
        CanonicalOhlcvWriterReceiptConsumerIntegrityError,
        match="receipt_cas_readback_failed",
    ):
        _ = capture.writer_receipt


def test_post_return_capture_key_substitution_is_rejected(
    raw_client: redis.Redis,
    tmp_path: Path,
) -> None:
    _publish(raw_client)
    capture, _store = _consume(raw_client, tmp_path)

    with pytest.raises(CanonicalOhlcvWriterReceiptConsumerIntegrityError):
        substituted = replace(
            capture,
            source_key="v2:market:ohlcv_closed:binance:ETHUSDT:4h",
        )
        _ = substituted.tuple_manifest


def test_discovery_clock_after_authoritative_clock_is_rejected(
    raw_client: redis.Redis,
    tmp_path: Path,
) -> None:
    _publish(raw_client)
    now_seconds = int(time.time())
    proxy = _ClientProxy(
        raw_client,
        time_overrides={1: (now_seconds + 600, 0)},
    )

    with pytest.raises(
        CanonicalOhlcvWriterReceiptConsumerValidationError,
        match="clock_order_invalid",
    ):
        _consume(proxy, tmp_path)
