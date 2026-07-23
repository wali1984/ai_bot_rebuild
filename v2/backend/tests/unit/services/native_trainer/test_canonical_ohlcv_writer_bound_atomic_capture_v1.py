from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime
from itertools import pairwise
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
    canonical_ohlcv_writer_bound_atomic_capture_v1 as composite_module,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_atomic_receipt_adapter import (
    CanonicalOhlcvAtomicCaptureIntegrityError,
    CanonicalOhlcvAtomicCaptureTransportError,
    CanonicalOhlcvAtomicCaptureValidationError,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_writer_bound_atomic_capture_v1 import (
    CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_CAPTURE_SCHEMA_VERSION,
    CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_DOWNSTREAM_STATUS,
    CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_EVIDENCE_CLASSIFICATION,
    CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_MANIFEST_SCHEMA_VERSION,
    CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError,
    CanonicalOhlcvWriterBoundAtomicCaptureTransportError,
    CanonicalOhlcvWriterBoundAtomicCaptureValidationError,
    capture_canonical_ohlcv_writer_bound_atomic,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_writer_receipt_consumer_v1 import (
    BINANCE_REST_WRITER_ROLE,
    BINANCE_WSS_WRITER_ROLE,
    CanonicalOhlcvWriterReceiptConsumerIntegrityError,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
)

SYMBOL = "BTCUSDT"
TIMEFRAME = "4h"
CANONICAL_KEY = "v2:market:ohlcv_closed:binance:BTCUSDT:4h"
WSS_CODE_SHA256 = "1" * 64
REST_CODE_SHA256 = "2" * 64
CONFIG_A_SHA256 = "3" * 64
CONFIG_B_SHA256 = "4" * 64
MUTABLE_TTL_SECONDS = 86_400
RECEIPT_TTL_SECONDS = 43_200
ARCHIVE_TTL_SECONDS = 57_600
ROW_COUNT = 71
_CLOCK_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_AUTHORITY_FIELDS = (
    "durable_ledger_appended",
    "feature_snapshot_published",
    "feature_publication_receipt_emitted",
    "consumer_eligible",
    "trainer_admission_granted",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
)
_UNWIRED_FIELDS = (
    "market_performance_thresholds_applied",
    "runtime_wired",
)


def _allowlist() -> dict[str, tuple[str, ...]]:
    return {
        BINANCE_WSS_WRITER_ROLE: (WSS_CODE_SHA256,),
        BINANCE_REST_WRITER_ROLE: (REST_CODE_SHA256,),
    }


def _rows(*, changed_latest: bool = False) -> list[dict[str, Any]]:
    duration_ms = TIMEFRAME_DURATION_MS[TIMEFRAME]
    now_ms = int(time.time() * 1_000)
    latest_close = (now_ms // duration_ms) * duration_ms - 1
    first_open = latest_close + 1 - ROW_COUNT * duration_ms
    rows: list[dict[str, Any]] = []
    for index in range(ROW_COUNT):
        open_time = first_open + index * duration_ms
        close_time = open_time + duration_ms - 1
        changed = changed_latest and index == ROW_COUNT - 1
        source = [
            open_time,
            "100.0",
            "104.0" if changed else "103.0",
            "99.0",
            "103.0" if changed else "102.0",
            "12.0",
            close_time,
            "1236.0" if changed else "1224.0",
            10,
            "6.0",
            "612.0",
            "0",
        ]
        rows.append(
            canonical_from_binance_rest(
                source,
                symbol=SYMBOL,
                timeframe=TIMEFRAME,
                ingested_at=close_time + 1,
            ).to_dict()
        )
    return rows


def _publish(
    client: redis.Redis,
    *,
    rows: list[dict[str, Any]] | None = None,
    producer_role: str = BINANCE_WSS_WRITER_ROLE,
    producer_code_sha256: str = WSS_CODE_SHA256,
    producer_config_sha256: str = CONFIG_A_SHA256,
) -> Any:
    return atomic_merge_closed_window(
        client,
        redis_key=CANONICAL_KEY,
        new_rows=tuple(_rows() if rows is None else rows),
        producer_role=producer_role,
        producer_code_sha256=producer_code_sha256,
        producer_config_sha256=producer_config_sha256,
        receipt_ttl_seconds=RECEIPT_TTL_SECONDS,
        archive_ttl_seconds=ARCHIVE_TTL_SECONDS,
        ttl_policy="set",
        ttl_seconds=MUTABLE_TTL_SECONDS,
    )


@pytest.fixture(scope="module")
def redis_socket(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    executable = shutil.which("redis-server")
    if executable is None:
        pytest.skip("redis-server is required for the composite receipt tests")
    root = tmp_path_factory.mktemp("writer-bound-atomic-redis")
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


def _capture(
    client: Any,
    tmp_path: Path,
    *,
    store: ImmutableSourcePayloadStore | None = None,
    max_attempts: int = 4,
) -> tuple[Any, ImmutableSourcePayloadStore]:
    resolved_store = store or ImmutableSourcePayloadStore(tmp_path / "source-payloads")
    capture = capture_canonical_ohlcv_writer_bound_atomic(
        client,
        resolved_store,
        expected_symbol=SYMBOL,
        expected_timeframe=TIMEFRAME,
        trusted_writer_code_sha256_by_role=_allowlist(),
        max_attempts=max_attempts,
    )
    return capture, resolved_store


def _parse_clock(value: str) -> datetime:
    return datetime.strptime(value, _CLOCK_FORMAT).replace(tzinfo=UTC)


def _corrupt(store: ImmutableSourcePayloadStore, address: SourcePayloadAddress) -> None:
    original = store.get(
        address.payload_sha256,
        expected_byte_count=address.payload_byte_count,
    )
    path = store.path_for(address.payload_sha256)
    corrupted = bytes([original[0] ^ 1]) + original[1:]
    os.chmod(path, 0o600)
    path.write_bytes(corrupted)
    os.chmod(path, 0o400)


@pytest.mark.parametrize(
    ("producer_role", "producer_code_sha256"),
    [
        (BINANCE_WSS_WRITER_ROLE, WSS_CODE_SHA256),
        (BINANCE_REST_WRITER_ROLE, REST_CODE_SHA256),
    ],
)
def test_real_writer_sandwich_binds_exact_atomic_receipts_manifests_and_clocks(
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

    capture, store = _capture(raw_client, tmp_path)
    manifest = capture.composite_manifest
    clock_chain = (
        capture.feature_cutoff,
        capture.max_producer_event_time,
        capture.max_ingested_at,
        capture.max_source_available_at,
        capture.writer_publication_available_at,
        capture.pre_writer_discovery_observed_at,
        capture.pre_writer_authoritative_observed_at,
        capture.pre_writer_consumer_observed_at,
        capture.atomic_server_observed_at,
        capture.atomic_consumer_observed_at,
        capture.post_writer_discovery_observed_at,
        capture.post_writer_authoritative_observed_at,
        capture.post_writer_consumer_observed_at,
        capture.generated_at,
    )

    assert capture.schema_version == (CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_CAPTURE_SCHEMA_VERSION)
    assert capture.manifest_schema_version == (
        CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_MANIFEST_SCHEMA_VERSION
    )
    assert capture.evidence_classification == (
        CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_EVIDENCE_CLASSIFICATION
    )
    assert capture.downstream_status == (CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_DOWNSTREAM_STATUS)
    assert capture.attempt_count == 1
    assert capture.publication_race_retry_count == 0
    assert capture.revision_id == publication.revision_id
    assert capture.producer_role == producer_role
    assert capture.producer_code_sha256 == producer_code_sha256
    assert capture.row_count == ROW_COUNT
    assert capture.exact_canonical_payload_bytes == raw_client.get(CANONICAL_KEY)
    assert capture.pre_writer_capture.exact_canonical_payload_bytes == (
        capture.atomic_capture.exact_full_source_payload_bytes
    )
    assert capture.atomic_capture.exact_full_source_payload_bytes == (
        capture.post_writer_capture.exact_canonical_payload_bytes
    )
    assert capture.pre_writer_capture.writer_receipt_sha256 == (
        capture.post_writer_capture.writer_receipt_sha256
    )
    assert capture.pre_writer_tuple_manifest_sha256 == (
        capture.pre_writer_tuple_manifest_address.payload_sha256
    )
    assert capture.atomic_suffix_manifest_sha256 == (
        capture.atomic_suffix_manifest_address.payload_sha256
    )
    assert capture.post_writer_tuple_manifest_sha256 == (
        capture.post_writer_tuple_manifest_address.payload_sha256
    )
    assert len(capture.ordered_selected_candle_receipt_sha256s) == ROW_COUNT
    assert capture.ordered_selected_candle_receipt_sha256s == tuple(
        receipt.receipt_sha256 for receipt in capture.atomic_capture.source_read_receipts
    )
    assert all(
        earlier <= later for earlier, later in pairwise(tuple(map(_parse_clock, clock_chain)))
    )
    assert capture.generated_at_ms == int(_parse_clock(capture.generated_at).timestamp() * 1_000)
    assert capture.available_at is None
    assert capture.decision_time is None
    assert capture.execution_time is None
    assert manifest["available_at"] is None
    assert manifest["decision_time"] is None
    assert manifest["execution_time"] is None
    assert manifest["pre_writer_tuple_manifest_sha256"] == (
        capture.pre_writer_tuple_manifest_sha256
    )
    assert manifest["atomic_suffix_manifest_sha256"] == (capture.atomic_suffix_manifest_sha256)
    assert manifest["post_writer_tuple_manifest_sha256"] == (
        capture.post_writer_tuple_manifest_sha256
    )
    assert manifest["ordered_selected_candle_receipt_sha256s"] == list(
        capture.ordered_selected_candle_receipt_sha256s
    )
    assert hashlib.sha256(capture.composite_manifest_json.encode("ascii")).hexdigest() == (
        capture.composite_manifest_sha256
    )
    assert store.get(
        capture.composite_manifest_address.payload_sha256,
        expected_byte_count=capture.composite_manifest_byte_count,
    ) == capture.composite_manifest_json.encode("ascii")


def test_all_authority_is_frozen_false_and_unwired(
    raw_client: redis.Redis,
    tmp_path: Path,
) -> None:
    _publish(raw_client)
    capture, _store = _capture(raw_client, tmp_path)

    assert all(getattr(capture, name) is False for name in _AUTHORITY_FIELDS)
    assert all(capture.composite_manifest[name] is False for name in _AUTHORITY_FIELDS)
    assert all(getattr(capture, name) is False for name in _UNWIRED_FIELDS)
    assert all(capture.composite_manifest[name] is False for name in _UNWIRED_FIELDS)
    assert not hasattr(capture, "publish")
    assert not hasattr(capture, "train")
    assert not hasattr(capture, "predict")
    with pytest.raises(FrozenInstanceError):
        capture.trainer_admission_granted = True  # type: ignore[misc]

    object.__setattr__(capture, "trainer_admission_granted", True)
    with pytest.raises(
        CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError,
        match="capture_contract_invalid",
    ):
        _ = capture.composite_manifest


@pytest.mark.parametrize(
    ("same_bytes", "exhaust"),
    [
        (False, False),
        (False, True),
        (True, False),
        (True, True),
    ],
    ids=(
        "different-bytes-success",
        "different-bytes-exhaustion",
        "same-bytes-new-revision-success",
        "same-bytes-new-revision-exhaustion",
    ),
)
def test_cross_proof_publication_races_are_retried_and_bounded(
    raw_client: redis.Redis,
    tmp_path: Path,
    same_bytes: bool,
    exhaust: bool,
) -> None:
    base_rows = _rows()
    changed_rows = _rows(changed_latest=True)
    initial = _publish(raw_client, rows=base_rows)
    publications = [initial]
    change_calls = {3, 8} if exhaust else {3}

    def before_execute(call_number: int) -> None:
        if call_number not in change_calls:
            return
        publication_index = len(publications)
        if same_bytes:
            config = CONFIG_B_SHA256 if publication_index % 2 == 1 else CONFIG_A_SHA256
            publications.append(
                _publish(
                    raw_client,
                    rows=base_rows,
                    producer_config_sha256=config,
                )
            )
            return
        assert raw_client.delete(CANONICAL_KEY) == 1
        rows = changed_rows if publication_index % 2 == 1 else base_rows
        publications.append(_publish(raw_client, rows=rows))

    proxy = _ClientProxy(raw_client, before_execute=before_execute)
    if exhaust:
        with pytest.raises(
            CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError,
            match="publication_race_retry_exhausted",
        ):
            _capture(proxy, tmp_path, max_attempts=2)
        assert proxy.pipeline_calls == 10
        return

    capture, _store = _capture(proxy, tmp_path, max_attempts=2)
    assert proxy.pipeline_calls == 10
    assert capture.attempt_count == 2
    assert capture.publication_race_retry_count == 1
    assert capture.revision_id == publications[-1].revision_id
    assert capture.pre_writer_capture.revision_id == (capture.post_writer_capture.revision_id)


@pytest.mark.parametrize(
    "reason",
    [
        "canonical_ohlcv_consumer_pointer_race_retry_exhausted",
        "canonical_ohlcv_consumer_prepare_race_retry_exhausted",
    ],
)
def test_exact_writer_child_race_allowlist_retries_then_succeeds(
    raw_client: redis.Redis,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    _publish(raw_client)
    original = composite_module.consume_current_canonical_ohlcv_writer_receipt
    calls = 0

    def flaky(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise CanonicalOhlcvWriterReceiptConsumerIntegrityError(reason)
        return original(*args, **kwargs)

    monkeypatch.setattr(
        composite_module,
        "consume_current_canonical_ohlcv_writer_receipt",
        flaky,
    )
    capture, _store = _capture(raw_client, tmp_path, max_attempts=2)

    assert calls == 3
    assert capture.attempt_count == 2


@pytest.mark.parametrize(
    "reason",
    [
        "canonical_ohlcv_consumer_pointer_race_retry_exhausted",
        "canonical_ohlcv_consumer_prepare_race_retry_exhausted",
    ],
)
def test_exact_writer_child_race_allowlist_has_composite_exhaustion_bound(
    raw_client: redis.Redis,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    _publish(raw_client)
    calls = 0

    def always_racing(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise CanonicalOhlcvWriterReceiptConsumerIntegrityError(reason)

    monkeypatch.setattr(
        composite_module,
        "consume_current_canonical_ohlcv_writer_receipt",
        always_racing,
    )
    with pytest.raises(
        CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError,
        match="publication_race_retry_exhausted",
    ):
        _capture(raw_client, tmp_path, max_attempts=2)
    assert calls == 2


@pytest.mark.parametrize(
    "reason",
    [
        "canonical_ohlcv_consumer_read_retry_exhausted",
        "canonical_ohlcv_consumer_pointer_value_tampered",
    ],
)
def test_nonallowlisted_writer_integrity_failure_is_not_retried(
    raw_client: redis.Redis,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    _publish(raw_client)
    calls = 0

    def tampered(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise CanonicalOhlcvWriterReceiptConsumerIntegrityError(reason)

    monkeypatch.setattr(
        composite_module,
        "consume_current_canonical_ohlcv_writer_receipt",
        tampered,
    )
    with pytest.raises(
        CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError,
        match="writer_integrity_failed",
    ):
        _capture(raw_client, tmp_path, max_attempts=4)
    assert calls == 1


@pytest.mark.parametrize(
    ("child_error", "composite_error", "reason"),
    [
        (
            CanonicalOhlcvAtomicCaptureValidationError,
            CanonicalOhlcvWriterBoundAtomicCaptureValidationError,
            "atomic_validation_failed",
        ),
        (
            CanonicalOhlcvAtomicCaptureIntegrityError,
            CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError,
            "atomic_integrity_failed",
        ),
        (
            CanonicalOhlcvAtomicCaptureTransportError,
            CanonicalOhlcvWriterBoundAtomicCaptureTransportError,
            "atomic_transport_failed",
        ),
    ],
)
def test_atomic_child_failures_are_totalized_and_never_retried(
    raw_client: redis.Redis,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    child_error: type[Exception],
    composite_error: type[Exception],
    reason: str,
) -> None:
    _publish(raw_client)
    calls = 0

    def fail_atomic(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise child_error("hostile child detail")

    monkeypatch.setattr(
        composite_module,
        "capture_canonical_closed_ohlcv_atomic_receipts",
        fail_atomic,
    )
    with pytest.raises(composite_error, match=reason) as exc_info:
        _capture(raw_client, tmp_path, max_attempts=4)
    assert calls == 1
    assert "hostile child detail" not in str(exc_info.value)


def test_atomic_redis_clock_after_atomic_consumer_clock_fails_composite_order(
    raw_client: redis.Redis,
    tmp_path: Path,
) -> None:
    _publish(raw_client)
    future_seconds = int(time.time()) + 600
    proxy = _ClientProxy(
        raw_client,
        time_overrides={3: (future_seconds, 0)},
    )

    with pytest.raises(
        CanonicalOhlcvWriterBoundAtomicCaptureValidationError,
        match="clock_order_invalid",
    ):
        _capture(proxy, tmp_path)
    assert proxy.pipeline_calls == 5


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("source_key", "v2:market:ohlcv_closed:binance:ETHUSDT:4h"),
        ("revision_id", f"v2_ohlcv_closed_{'f' * 64}"),
        ("exact_payload_sha256", "f" * 64),
        ("pre_writer_tuple_manifest_sha256", "f" * 64),
        ("atomic_batch_material_sha256", "f" * 64),
        ("atomic_suffix_manifest_sha256", "f" * 64),
        ("post_writer_tuple_manifest_sha256", "f" * 64),
        ("available_at", "2099-01-01T00:00:00.000000Z"),
    ],
)
def test_post_return_field_and_child_manifest_substitutions_fail_closed(
    raw_client: redis.Redis,
    tmp_path: Path,
    field_name: str,
    replacement: object,
) -> None:
    _publish(raw_client)
    capture, _store = _capture(raw_client, tmp_path)

    with pytest.raises(CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError):
        replace(capture, **{field_name: replacement})


def test_post_return_genuine_child_from_new_same_byte_revision_cannot_be_substituted(
    raw_client: redis.Redis,
    tmp_path: Path,
) -> None:
    rows = _rows()
    first_publication = _publish(raw_client, rows=rows)
    store = ImmutableSourcePayloadStore(tmp_path / "source-payloads")
    first, _store = _capture(raw_client, tmp_path, store=store)
    second_publication = _publish(
        raw_client,
        rows=rows,
        producer_config_sha256=CONFIG_B_SHA256,
    )
    second, _store = _capture(raw_client, tmp_path, store=store)
    assert first_publication.revision_id != second_publication.revision_id
    assert first.exact_payload_sha256 == second.exact_payload_sha256

    with pytest.raises(
        CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError,
        match="post_return_child_mismatch",
    ):
        replace(first, _post_writer_capture=second._post_writer_capture)


@pytest.mark.parametrize(
    "target",
    [
        "canonical_payload",
        "pre_writer_manifest",
        "atomic_suffix_manifest",
        "post_writer_manifest",
        "composite_manifest",
    ],
)
def test_child_and_composite_cas_corruption_is_detected_on_fresh_access(
    raw_client: redis.Redis,
    tmp_path: Path,
    target: str,
) -> None:
    _publish(raw_client)
    capture, store = _capture(raw_client, tmp_path)
    addresses = {
        "canonical_payload": capture.canonical_payload_address,
        "pre_writer_manifest": capture.pre_writer_tuple_manifest_address,
        "atomic_suffix_manifest": capture.atomic_suffix_manifest_address,
        "post_writer_manifest": capture.post_writer_tuple_manifest_address,
        "composite_manifest": capture.composite_manifest_address,
    }
    _corrupt(store, addresses[target])

    with pytest.raises(CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError):
        _ = capture.composite_manifest


def test_capture_shape_retains_explicit_non_authority_clocks(
    raw_client: redis.Redis,
    tmp_path: Path,
) -> None:
    _publish(raw_client)
    capture, _store = _capture(raw_client, tmp_path)
    field_names = {item.name for item in fields(capture)}

    assert "generated_at" in field_names
    assert "generated_at_ms" in field_names
    assert "available_at" in field_names
    assert "decision_time" in field_names
    assert "execution_time" in field_names
    assert "composite_completed_at" not in field_names
    assert "composite_completed_at_ms" not in field_names
    assert capture.composite_manifest["generated_at"] == capture.generated_at
