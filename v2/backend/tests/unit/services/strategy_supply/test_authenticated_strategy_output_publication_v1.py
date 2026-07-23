from __future__ import annotations

import inspect
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import redis

from v2.backend.app.services.strategy_supply import (
    authenticated_strategy_output_publication_v1 as publication_module,
)
from v2.backend.app.services.strategy_supply.authenticated_strategy_output_publication_v1 import (
    STRATEGY_OUTPUT_ENVELOPE_SCHEMA_VERSION,
    STRATEGY_OUTPUT_PAPER_ADMISSION_SCHEMA_VERSION,
    STRATEGY_OUTPUT_PUBLICATION_RECEIPT_SCHEMA_VERSION,
    StrategyOutputPublicationV1IntegrityError,
    StrategyOutputPublicationV1TransportError,
    StrategyOutputPublicationV1ValidationError,
    assess_authenticated_strategy_output_for_paper_v1,
    publish_and_verify_authenticated_strategy_output_v1,
)
from v2.backend.tests.unit.services.strategy_supply import (
    test_authenticated_strategy_ta_transform_v1 as ta_test,
)

_CLOCK_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_ARCHIVE_TTL_SECONDS = 7_200
_RECEIPT_TTL_SECONDS = 600
_LEGACY_KEY_PREFIXES = (
    "v2:strategy_supply:hypotheses:",
    "v2:strategy_supply:positive_hypotheses:",
    "v2:strategy_supply:gate_clean_positive_hypotheses:",
)


def _clock(value: str) -> datetime:
    return datetime.strptime(value, _CLOCK_FORMAT).replace(tzinfo=UTC)


def _after(value: str, *, milliseconds: int = 1) -> datetime:
    return _clock(value) + timedelta(milliseconds=milliseconds)


@pytest.fixture(scope="module")
def redis_socket(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    executable = shutil.which("redis-server")
    if executable is None:
        pytest.skip("redis-server is required for strategy output receipt tests")
    root = tmp_path_factory.mktemp("authenticated-strategy-output-redis")
    socket_path = str(root / "redis.sock")
    process = subprocess.Popen(  # noqa: S603 - fixed local executable and arguments
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
            client = redis.Redis(unix_socket_path=socket_path, decode_responses=False)
            if client.ping():
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


@pytest.fixture(scope="module")
def genuine_transform(
    redis_socket: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> Any:
    client = redis.Redis(unix_socket_path=redis_socket, decode_responses=False)
    client.flushdb()
    ta_test._publish(
        client,
        rows=ta_test._rows(source="wss"),
        producer_role=ta_test.BINANCE_WSS_WRITER_ROLE,
        producer_code_sha256=ta_test.WSS_CODE_SHA256,
    )
    root = tmp_path_factory.mktemp("authenticated-strategy-output-transform")
    capture, _source_store = ta_test._capture(client, root / "source")
    transform, _output_store = ta_test._transform(capture, root / "output")
    return transform


class _FakeRedis:
    def __init__(self, *, start: datetime) -> None:
        self.store: dict[str, bytes] = {}
        self.types: dict[str, str] = {}
        self.clock_us = int(start.timestamp() * 1_000_000)
        self.time_calls = 0
        self.eval_calls = 0
        self.before_prepare_readback: Callable[[_FakeRedis, str, str], None] | None = None
        self.before_commit: Callable[[_FakeRedis, str, str], None] | None = None
        self.before_reopen: Callable[[_FakeRedis, list[str]], None] | None = None

    @staticmethod
    def _raw(value: object) -> bytes:
        if type(value) is bytes:
            return value
        if type(value) is str:
            return value.encode("ascii")
        raise AssertionError(f"unexpected fake Redis value: {type(value)!r}")

    def _time(self) -> tuple[str, str]:
        self.time_calls += 1
        self.clock_us += 1_000
        return str(self.clock_us // 1_000_000), str(self.clock_us % 1_000_000)

    def _type(self, key: str) -> str:
        if key in self.types:
            return self.types[key]
        return "string" if key in self.store else "none"

    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> list[object]:
        self.eval_calls += 1
        keys = [str(value) for value in keys_and_args[:numkeys]]
        args = list(keys_and_args[numkeys:])
        if "authenticated_strategy_output_prepare_v1" in script:
            archive_key, latest_key, receipt_key, pointer_key = keys
            payload = self._raw(args[0])
            archive_ttl = int(args[1])
            receipt_ttl = int(args[2])
            maximum = int(args[3])
            cutoff_us = int(args[4])
            generated_us = int(args[5])
            output_id = self._raw(args[6])
            if archive_ttl <= receipt_ttl:
                return ["ERROR", "STRATEGY_OUTPUT_ARCHIVE_TTL_MUST_EXCEED_RECEIPT_TTL"]
            if len(payload) > maximum:
                return ["ERROR", "STRATEGY_OUTPUT_ARGUMENT_OVERSIZED"]
            before_seconds, before_micros = self._time()
            before_us = int(before_seconds) * 1_000_000 + int(before_micros)
            if cutoff_us > before_us:
                return ["ERROR", "STRATEGY_OUTPUT_FEATURE_CUTOFF_AFTER_REDIS_PREWRITE_CLOCK"]
            if generated_us > before_us:
                return ["ERROR", "STRATEGY_OUTPUT_GENERATED_AT_AFTER_REDIS_PREWRITE_CLOCK"]
            for key, reason in (
                (archive_key, "STRATEGY_OUTPUT_ARCHIVE_TYPE_INVALID"),
                (latest_key, "STRATEGY_OUTPUT_LATEST_TYPE_INVALID"),
                (receipt_key, "STRATEGY_OUTPUT_RECEIPT_TYPE_INVALID"),
            ):
                if self._type(key) not in {"none", "string"}:
                    return ["ERROR", reason]
            if receipt_key in self.store:
                if self.store.get(archive_key) != payload or self.store.get(latest_key) != payload:
                    return ["ERROR", "STRATEGY_OUTPUT_EXISTING_PAYLOAD_IDENTITY_MISMATCH"]
                if self.store.get(pointer_key) != output_id:
                    return ["ERROR", "STRATEGY_OUTPUT_EXISTING_POINTER_IDENTITY_MISMATCH"]
                seconds, micros = self._time()
                return ["EXISTING", seconds, micros]
            existing = self.store.get(archive_key)
            if existing is not None and existing != payload:
                return ["ERROR", "STRATEGY_OUTPUT_ARCHIVE_IDENTITY_CONFLICT"]
            self.store.setdefault(archive_key, payload)
            self.store[latest_key] = payload
            if self.before_prepare_readback is not None:
                self.before_prepare_readback(self, archive_key, latest_key)
            if self.store.get(archive_key) != payload:
                return ["ERROR", "STRATEGY_OUTPUT_ARCHIVE_PREPARE_READBACK_MISMATCH"]
            if self.store.get(latest_key) != payload:
                return ["ERROR", "STRATEGY_OUTPUT_LATEST_PREPARE_READBACK_MISMATCH"]
            seconds, micros = self._time()
            return ["PREPARED", seconds, micros]
        if "authenticated_strategy_output_commit_receipt_v1" in script:
            archive_key, latest_key, receipt_key, pointer_key = keys
            output_payload = self._raw(args[0])
            receipt_payload = self._raw(args[1])
            output_id = self._raw(args[5])
            if self.before_commit is not None:
                self.before_commit(self, archive_key, latest_key)
            if self.store.get(archive_key) != output_payload:
                return ["ERROR", "STRATEGY_OUTPUT_CHANGED_BEFORE_RECEIPT_COMMIT"]
            if self.store.get(latest_key) != output_payload:
                return ["ERROR", "STRATEGY_OUTPUT_LATEST_CHANGED_BEFORE_RECEIPT_COMMIT"]
            existing = self.store.get(receipt_key)
            if existing is not None and existing != receipt_payload:
                return ["ERROR", "STRATEGY_OUTPUT_RECEIPT_IDENTITY_CONFLICT"]
            self.store.setdefault(receipt_key, receipt_payload)
            self.store[pointer_key] = output_id
            seconds, micros = self._time()
            return ["IDEMPOTENT" if existing is not None else "COMMITTED", seconds, micros]
        if "authenticated_strategy_output_reopen_v1" in script:
            archive_key, latest_key, receipt_key, pointer_key = keys
            output_id = self._raw(args[0])
            if self.before_reopen is not None:
                self.before_reopen(self, keys)
            missing_reasons = (
                (archive_key, "STRATEGY_OUTPUT_ARCHIVE_MISSING"),
                (latest_key, "STRATEGY_OUTPUT_LATEST_MISSING"),
                (receipt_key, "STRATEGY_OUTPUT_RECEIPT_MISSING"),
                (pointer_key, "STRATEGY_OUTPUT_POINTER_MISSING"),
            )
            for key, reason in missing_reasons:
                if key not in self.store:
                    return ["ERROR", reason]
            if self.store[pointer_key] != output_id:
                return ["ERROR", "STRATEGY_OUTPUT_POINTER_IDENTITY_MISMATCH"]
            seconds, micros = self._time()
            return [
                "REOPENED",
                self.store[archive_key],
                self.store[latest_key],
                self.store[receipt_key],
                self.store[pointer_key],
                seconds,
                micros,
            ]
        raise AssertionError("unexpected Lua script")


def _publication_clock(transform: Any) -> datetime:
    return _after(transform.transform_generated_at, milliseconds=1)


def _fake_for(transform: Any, *, milliseconds_after_generation: int = 100) -> _FakeRedis:
    return _FakeRedis(
        start=_after(
            transform.transform_generated_at,
            milliseconds=milliseconds_after_generation,
        )
    )


def _publish_fake(client: _FakeRedis, transform: Any) -> Any:
    observed = _publication_clock(transform)
    return publish_and_verify_authenticated_strategy_output_v1(
        client,
        transform,
        archive_ttl_seconds=_ARCHIVE_TTL_SECONDS,
        receipt_ttl_seconds=_RECEIPT_TTL_SECONDS,
        publication_clock=lambda: observed,
    )


def test_exact_held_output_receipt_and_paper_assessment(
    genuine_transform: Any,
) -> None:
    client = _fake_for(genuine_transform)
    result = _publish_fake(client, genuine_transform)
    envelope = result.envelope
    receipt = result.receipt

    assert envelope["schema_version"] == STRATEGY_OUTPUT_ENVELOPE_SCHEMA_VERSION
    assert receipt["schema_version"] == STRATEGY_OUTPUT_PUBLICATION_RECEIPT_SCHEMA_VERSION
    assert envelope["strategy_candidates"] == []
    assert envelope["authenticated_adaptive_policy_receipt_sha256"] is None
    assert envelope["market_performance_thresholds_applied"] == []
    assert envelope["unreceipted_external_economics_consumed"] == []
    assert envelope["available_at"] is None
    assert envelope["decision_time"] is None
    assert envelope["execution_time"] is None
    assert result.strategy_candidate_count == 0
    assert result.authenticated_adaptive_policy_attached is False
    assert result.strategy_output_authorized is False
    assert result.paper_trading_authorized is False
    assert result.live_execution_authorized is False
    assert result.order_submission_authorized is False
    assert result.decision_time is None
    assert result.execution_time is None
    assert set(client.store) == {
        result.archive_key,
        result.latest_projection_key,
        result.receipt_key,
        result.latest_receipt_pointer_key,
    }
    assert client.eval_calls == 3
    assert client.time_calls == 4
    clocks = (
        genuine_transform.feature_cutoff,
        genuine_transform.max_source_available_at,
        genuine_transform.writer_publication_available_at,
        genuine_transform.capture_generated_at,
        genuine_transform.transform_generated_at,
        result.generated_at,
        result.available_at,
        result.receipt_postcommit_observed_at,
        result.consumer_reopened_at,
    )
    assert all(
        _clock(left) <= _clock(right) for left, right in zip(clocks, clocks[1:], strict=False)
    )

    decision = _after(result.consumer_reopened_at, milliseconds=1)
    admission = assess_authenticated_strategy_output_for_paper_v1(
        result,
        decision_clock=lambda: decision,
    )
    assert admission.evidence["schema_version"] == STRATEGY_OUTPUT_PAPER_ADMISSION_SCHEMA_VERSION
    assert admission.rejection_reasons == (
        "authenticated_adaptive_strategy_policy_missing",
        "strategy_candidate_missing",
    )
    assert admission.accepted is False
    assert admission.paper_only is True
    assert admission.paper_trading_authorized is False
    assert admission.live_execution_authorized is False
    assert admission.order_submission_authorized is False
    assert admission.execution_time is None


def test_real_redis_exact_four_object_publication(
    redis_socket: str,
    genuine_transform: Any,
) -> None:
    client = redis.Redis(unix_socket_path=redis_socket, decode_responses=False)
    client.flushdb()
    fixed_generation = _publication_clock(genuine_transform)
    result = publish_and_verify_authenticated_strategy_output_v1(
        client,
        genuine_transform,
        archive_ttl_seconds=_ARCHIVE_TTL_SECONDS,
        receipt_ttl_seconds=_RECEIPT_TTL_SECONDS,
        publication_clock=lambda: fixed_generation,
    )

    assert client.get(result.archive_key) == result._envelope_json.encode("ascii")
    assert client.get(result.latest_projection_key) == result._envelope_json.encode("ascii")
    assert client.get(result.receipt_key) == result._receipt_json.encode("ascii")
    assert client.get(result.latest_receipt_pointer_key) == result.output_id.encode("ascii")
    assert client.ttl(result.archive_key) > client.ttl(result.receipt_key) > 0
    assert result.feature_cutoff <= result.available_at
    assert result.available_at <= result.receipt_postcommit_observed_at
    assert result.receipt_postcommit_observed_at <= result.consumer_reopened_at

    persisted = {key: client.get(key) for key in client.scan_iter("v2:strategy_supply:*")}
    reopened = publish_and_verify_authenticated_strategy_output_v1(
        client,
        genuine_transform,
        archive_ttl_seconds=_ARCHIVE_TTL_SECONDS,
        receipt_ttl_seconds=_RECEIPT_TTL_SECONDS,
        publication_clock=lambda: fixed_generation,
    )
    assert reopened.output_id == result.output_id
    assert reopened.receipt_sha256 == result.receipt_sha256
    assert reopened.available_at == result.available_at
    assert {key: client.get(key) for key in client.scan_iter("v2:strategy_supply:*")} == persisted


@pytest.mark.parametrize(
    ("archive_ttl", "receipt_ttl"),
    [(0, 600), (600, 0), (600, 600), (599, 600), (True, 600)],
)
def test_invalid_ttl_contract_rejects_before_redis(
    genuine_transform: Any,
    archive_ttl: Any,
    receipt_ttl: Any,
) -> None:
    client = _fake_for(genuine_transform)
    with pytest.raises(
        StrategyOutputPublicationV1ValidationError,
        match="strategy_output_publication_ttl_invalid",
    ):
        publish_and_verify_authenticated_strategy_output_v1(
            client,
            genuine_transform,
            archive_ttl_seconds=archive_ttl,
            receipt_ttl_seconds=receipt_ttl,
            publication_clock=lambda: _publication_clock(genuine_transform),
        )
    assert client.eval_calls == 0
    assert client.store == {}


def test_factory_authenticated_transform_is_required(genuine_transform: Any) -> None:
    client = _fake_for(genuine_transform)
    with pytest.raises(
        StrategyOutputPublicationV1ValidationError,
        match="strategy_output_authenticated_ta_transform_required",
    ):
        publish_and_verify_authenticated_strategy_output_v1(
            client,
            object(),  # type: ignore[arg-type]
            archive_ttl_seconds=_ARCHIVE_TTL_SECONDS,
            receipt_ttl_seconds=_RECEIPT_TTL_SECONDS,
        )
    assert client.store == {}


@pytest.mark.parametrize("target", ["archive", "latest"])
def test_prepare_exact_readback_mutation_fails_closed(
    genuine_transform: Any,
    target: str,
) -> None:
    client = _fake_for(genuine_transform)

    def mutate(fake: _FakeRedis, archive_key: str, latest_key: str) -> None:
        fake.store[archive_key if target == "archive" else latest_key] = b'{"attacker":true}'

    client.before_prepare_readback = mutate
    expected = "ARCHIVE" if target == "archive" else "LATEST"
    with pytest.raises(StrategyOutputPublicationV1IntegrityError, match=expected):
        _publish_fake(client, genuine_transform)
    assert not any("receipt:" in key for key in client.store)


@pytest.mark.parametrize("target", ["archive", "latest"])
def test_mutation_between_prepare_and_receipt_commit_fails_closed(
    genuine_transform: Any,
    target: str,
) -> None:
    client = _fake_for(genuine_transform)

    def mutate(fake: _FakeRedis, archive_key: str, latest_key: str) -> None:
        fake.store[archive_key if target == "archive" else latest_key] = b'{"attacker":true}'

    client.before_commit = mutate
    expected = "CHANGED_BEFORE_RECEIPT_COMMIT"
    with pytest.raises(StrategyOutputPublicationV1IntegrityError, match=expected):
        _publish_fake(client, genuine_transform)


@pytest.mark.parametrize("target_index", [0, 1, 2, 3])
def test_missing_or_tampered_postcommit_object_fails_closed(
    genuine_transform: Any,
    target_index: int,
) -> None:
    client = _fake_for(genuine_transform)

    def remove(fake: _FakeRedis, keys: list[str]) -> None:
        del fake.store[keys[target_index]]

    client.before_reopen = remove
    with pytest.raises(StrategyOutputPublicationV1IntegrityError):
        _publish_fake(client, genuine_transform)


def test_future_generation_clock_rejects_without_writes(genuine_transform: Any) -> None:
    client = _fake_for(genuine_transform, milliseconds_after_generation=2)
    future = _after(genuine_transform.transform_generated_at, milliseconds=1_000)
    with pytest.raises(
        StrategyOutputPublicationV1IntegrityError,
        match="GENERATED_AT_AFTER_REDIS_PREWRITE_CLOCK",
    ):
        publish_and_verify_authenticated_strategy_output_v1(
            client,
            genuine_transform,
            archive_ttl_seconds=_ARCHIVE_TTL_SECONDS,
            receipt_ttl_seconds=_RECEIPT_TTL_SECONDS,
            publication_clock=lambda: future,
        )
    assert client.store == {}


def test_regressing_redis_clock_fails_closed(genuine_transform: Any) -> None:
    client = _fake_for(genuine_transform)
    original = client.clock_us
    observations = iter(
        (
            original + 10_000,
            original + 20_000,
            original + 15_000,
            original + 30_000,
        )
    )

    def regressing() -> tuple[str, str]:
        value = next(observations)
        client.time_calls += 1
        return str(value // 1_000_000), str(value % 1_000_000)

    client._time = regressing  # type: ignore[method-assign]
    with pytest.raises(
        StrategyOutputPublicationV1IntegrityError,
        match="strategy_output_publication_clock_order_invalid",
    ):
        _publish_fake(client, genuine_transform)


def test_same_transform_and_generation_clock_have_same_output_identity(
    genuine_transform: Any,
) -> None:
    first = _publish_fake(_fake_for(genuine_transform), genuine_transform)
    second = _publish_fake(_fake_for(genuine_transform), genuine_transform)

    assert first.output_id == second.output_id
    assert first.output_payload_sha256 == second.output_payload_sha256
    assert first._envelope_json == second._envelope_json
    assert first.receipt_sha256 == second.receipt_sha256


def test_identical_publication_is_idempotently_reopened_without_writes(
    genuine_transform: Any,
) -> None:
    client = _fake_for(genuine_transform)
    first = _publish_fake(client, genuine_transform)
    persisted = dict(client.store)
    second = _publish_fake(client, genuine_transform)

    assert client.store == persisted
    assert client.eval_calls == 5
    assert first.output_id == second.output_id
    assert first.output_payload_sha256 == second.output_payload_sha256
    assert first.receipt_sha256 == second.receipt_sha256
    assert first.available_at == second.available_at
    assert first.receipt_postcommit_observed_at < second.receipt_postcommit_observed_at
    assert second.receipt_postcommit_observed_at <= second.consumer_reopened_at


def test_retained_result_mutation_and_dataclass_replacement_fail(
    genuine_transform: Any,
) -> None:
    result = _publish_fake(_fake_for(genuine_transform), genuine_transform)
    with pytest.raises(
        StrategyOutputPublicationV1IntegrityError,
        match="result_binding_invalid",
    ):
        replace(result, output_payload_sha256="f" * 64)

    object.__setattr__(result, "_receipt_json", result._receipt_json[:-1] + "0")
    with pytest.raises(StrategyOutputPublicationV1IntegrityError):
        _ = result.receipt


def test_decision_before_publication_reopen_is_explicitly_rejected(
    genuine_transform: Any,
) -> None:
    result = _publish_fake(_fake_for(genuine_transform), genuine_transform)
    admission = assess_authenticated_strategy_output_for_paper_v1(
        result,
        decision_clock=lambda: _clock(result.available_at),
    )

    assert admission.accepted is False
    assert "publication_receipt_committed_after_decision_time" in admission.rejection_reasons
    assert "publication_reopened_after_decision_time" in admission.rejection_reasons
    assert admission.execution_time is None


def test_decision_at_reopen_equality_is_temporally_valid_but_policy_held(
    genuine_transform: Any,
) -> None:
    result = _publish_fake(_fake_for(genuine_transform), genuine_transform)
    admission = assess_authenticated_strategy_output_for_paper_v1(
        result,
        decision_clock=lambda: _clock(result.consumer_reopened_at),
    )

    assert admission.rejection_reasons == (
        "authenticated_adaptive_strategy_policy_missing",
        "strategy_candidate_missing",
    )
    assert admission.accepted is False


def test_public_api_cannot_accept_legacy_rows_or_mutable_economics() -> None:
    publish_signature = inspect.signature(publish_and_verify_authenticated_strategy_output_v1)
    admission_signature = inspect.signature(assess_authenticated_strategy_output_for_paper_v1)
    source = inspect.getsource(publication_module)

    assert tuple(publish_signature.parameters) == (
        "redis_client",
        "transform",
        "archive_ttl_seconds",
        "receipt_ttl_seconds",
        "publication_clock",
    )
    assert tuple(admission_signature.parameters) == ("publication", "decision_clock")
    assert not {
        "hypotheses",
        "strategy_candidates",
        "live_gate_state",
        "reference_notional",
        "risk_profile",
        "position_state",
    }.intersection(publish_signature.parameters)
    assert "v2:live_gate:state" not in source
    assert all(prefix not in source for prefix in _LEGACY_KEY_PREFIXES)


def test_redis_transport_failure_is_not_masked(genuine_transform: Any) -> None:
    class _BrokenRedis:
        def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
            raise ConnectionError("sentinel transport detail")

    with pytest.raises(
        StrategyOutputPublicationV1TransportError,
        match="strategy_output_redis_eval_failed",
    ):
        publish_and_verify_authenticated_strategy_output_v1(
            _BrokenRedis(),
            genuine_transform,
            archive_ttl_seconds=_ARCHIVE_TTL_SECONDS,
            receipt_ttl_seconds=_RECEIPT_TTL_SECONDS,
            publication_clock=lambda: _publication_clock(genuine_transform),
        )
