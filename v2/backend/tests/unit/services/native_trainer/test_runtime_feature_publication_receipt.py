from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import redis

from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4,
    FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
    REQUIREMENT_REQUIRED,
)
from v2.backend.app.services.native_trainer.runtime_feature_publication_receipt import (
    FEATURE_PUBLICATION_RECEIPT_EVIDENCE_CLASSIFICATION,
    FEATURE_PUBLICATION_RECEIPT_SCHEMA_VERSION,
    FeaturePublicationReceiptIntegrityError,
    FeaturePublicationReceiptValidationError,
    VerifiedFeaturePublication,
    derive_feature_publication_slot_bindings,
    publish_and_verify_feature_snapshot,
)

_START_US = 1_800_000_030_000_000
_CODE_SHA256 = "a" * 64
_CONFIG_SHA256 = "b" * 64


def _snapshot(
    *,
    stale: bool = False,
    missing_required: bool = False,
) -> str:
    features = {
        slot.feature_name: float(slot.ordinal + 1)
        for slot in FEATURE_SOURCE_REGISTRY_V4.slots
        if slot.requirement_class == REQUIREMENT_REQUIRED
    }
    if missing_required:
        features.pop(
            next(
                slot.feature_name
                for slot in FEATURE_SOURCE_REGISTRY_V4.slots
                if slot.requirement_class == REQUIREMENT_REQUIRED
            )
        )
    snapshot: dict[str, object] = {
        "schema_version": "v2_native_feature_snapshot_v2",
        "worker_id": "v2_feature_pipeline_native_loop",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "features": features,
        "feature_cutoff": "2027-01-15T08:00:29.999000Z",
        "candle_closed_confirmed": True,
        "latest_candle_temporally_valid": not stale,
        "exact_source_clock_valid": not stale,
        "trainer_consumable": False,
        "valid_for_prediction": False,
        "valid_for_paper": False,
    }
    identity_payload = json.dumps(snapshot, sort_keys=True).encode()
    snapshot["feature_snapshot_id"] = "v2_fsnap_" + hashlib.sha256(identity_payload).hexdigest()
    return json.dumps(snapshot)


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.clock_us = _START_US
        self.receipt_ttl_seconds: int | None = None
        self.before_commit: Callable[[_FakeRedis, str], None] | None = None
        self.before_reopen: Callable[[_FakeRedis, str, str], None] | None = None

    def _time(self) -> tuple[str, str]:
        self.clock_us += 1_000
        return str(self.clock_us // 1_000_000), str(self.clock_us % 1_000_000)

    @staticmethod
    def _raw(value: object) -> bytes:
        if type(value) is bytes:
            return value
        if type(value) is str:
            return value.encode()
        raise AssertionError(f"unexpected fake Redis value: {type(value)!r}")

    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> list[object]:
        keys = [str(value) for value in keys_and_args[:numkeys]]
        args = list(keys_and_args[numkeys:])
        if "native_feature_publication_prepare_v1" in script:
            archive_key, latest_key, receipt_key = keys
            payload = self._raw(args[0])
            assert type(args[3]) is int
            maximum = args[3]
            if len(payload) > maximum:
                return ["ERROR", "SNAPSHOT_ARGUMENT_OVERSIZED"]
            existing = self.store.get(archive_key)
            if existing is not None and existing != payload:
                return ["ERROR", "SNAPSHOT_ARCHIVE_IDENTITY_CONFLICT"]
            if receipt_key in self.store:
                return ["ERROR", "RECEIPT_ALREADY_EXISTS_USE_CONSUMER_REOPEN"]
            self.store.setdefault(archive_key, payload)
            self.store[latest_key] = payload
            seconds, microseconds = self._time()
            return ["PREPARED", seconds, microseconds]
        if "native_feature_publication_commit_receipt_v1" in script:
            archive_key, receipt_key, pointer_key = keys
            snapshot_payload = self._raw(args[0])
            receipt_payload = self._raw(args[1])
            assert type(args[2]) is int
            self.receipt_ttl_seconds = args[2]
            snapshot_id = self._raw(args[5])
            if self.before_commit is not None:
                self.before_commit(self, archive_key)
            if self.store.get(archive_key) != snapshot_payload:
                return ["ERROR", "SNAPSHOT_CHANGED_BEFORE_RECEIPT_COMMIT"]
            existing = self.store.get(receipt_key)
            if existing is not None and existing != receipt_payload:
                return ["ERROR", "RECEIPT_IDENTITY_CONFLICT"]
            self.store.setdefault(receipt_key, receipt_payload)
            self.store[pointer_key] = snapshot_id
            seconds, microseconds = self._time()
            return ["IDEMPOTENT" if existing is not None else "COMMITTED", seconds, microseconds]
        if "native_feature_publication_reopen_v1" in script:
            archive_key, receipt_key = keys
            if self.before_reopen is not None:
                self.before_reopen(self, archive_key, receipt_key)
            if archive_key not in self.store:
                return ["ERROR", "SNAPSHOT_ARCHIVE_MISSING"]
            if receipt_key not in self.store:
                return ["ERROR", "RECEIPT_MISSING"]
            seconds, microseconds = self._time()
            return [
                "REOPENED",
                self.store[archive_key],
                self.store[receipt_key],
                seconds,
                microseconds,
            ]
        raise AssertionError("unexpected Lua script")


def _publish(redis_client: _FakeRedis, payload: str) -> VerifiedFeaturePublication:
    return publish_and_verify_feature_snapshot(
        redis_client,
        payload,
        archive_ttl_seconds=43_200,
        latest_ttl_seconds=600,
        producer_code_sha256=_CODE_SHA256,
        producer_config_sha256=_CONFIG_SHA256,
    )


@pytest.fixture()  # type: ignore[misc]
def redis_socket(tmp_path: Path) -> Iterator[str]:
    executable = shutil.which("redis-server")
    if executable is None:
        pytest.skip("redis-server is required for the atomic Lua contract test")
    assert executable is not None
    socket_path = str(tmp_path / "redis.sock")
    process = subprocess.Popen(  # noqa: S603 - fixed local test executable/arguments
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
            str(tmp_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 5.0
    client: redis.Redis | None = None
    while time.monotonic() < deadline:
        try:
            client = redis.Redis(unix_socket_path=socket_path, decode_responses=True)
            if client.ping():
                break
        except (OSError, redis.RedisError):
            time.sleep(0.02)
    else:
        process.terminate()
        process.wait(timeout=5)
        pytest.fail("ephemeral redis-server did not become ready")
    assert client is not None
    client.flushdb()
    try:
        yield socket_path
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_exact_archive_adoption_refreshes_ttl_beyond_receipt_lifetime(
    redis_socket: str,
) -> None:
    client = redis.Redis(unix_socket_path=redis_socket, decode_responses=True)
    payload = _snapshot()
    snapshot_id = json.loads(payload)["feature_snapshot_id"]
    archive_key = f"v2:features:snapshot:{snapshot_id}"
    assert client.set(archive_key, payload, ex=1)

    result = publish_and_verify_feature_snapshot(
        client,
        payload,
        archive_ttl_seconds=43_200,
        latest_ttl_seconds=600,
        producer_code_sha256=_CODE_SHA256,
        producer_config_sha256=_CONFIG_SHA256,
    )

    assert client.ttl(result.snapshot_archive_key) > client.ttl(result.receipt_key)
    time.sleep(1.1)
    assert client.exists(result.snapshot_archive_key) == 1
    assert client.exists(result.receipt_key) == 1


def test_archive_ttl_must_exceed_receipt_lifetime() -> None:
    with pytest.raises(
        FeaturePublicationReceiptValidationError,
        match="FEATURE_PUBLICATION_TTL_INVALID",
    ):
        publish_and_verify_feature_snapshot(
            _FakeRedis(),
            _snapshot(),
            archive_ttl_seconds=600,
            latest_ttl_seconds=600,
            producer_code_sha256=_CODE_SHA256,
            producer_config_sha256=_CONFIG_SHA256,
        )


def test_complete_slot_receipt_is_postcommit_reopened_but_keeps_authority_held() -> None:
    redis_client = _FakeRedis()

    result = _publish(redis_client, _snapshot())

    receipt = result.receipt
    assert result.slot_count == FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT == 446
    assert result.complete_slot_coverage is True
    assert result.publication_binding_authenticated is True
    assert result.source_scope_complete is False
    assert result.per_field_source_receipts_complete is False
    assert result.trainer_admission_authorized is False
    assert result.prediction_authorized is False
    assert result.paper_trading_authorized is False
    assert result.live_execution_authorized is False
    assert receipt["schema_version"] == FEATURE_PUBLICATION_RECEIPT_SCHEMA_VERSION
    assert receipt["evidence_classification"] == (
        FEATURE_PUBLICATION_RECEIPT_EVIDENCE_CLASSIFICATION
    )
    assert receipt["complete_slot_coverage"] is True
    assert receipt["publication_binding_authenticated"] is True
    assert receipt["source_scope_complete"] is False
    assert receipt["per_field_source_receipts_complete"] is False
    assert receipt["slot_count"] == 446
    assert receipt["slot_binding_derivation_contract"].startswith("REOPEN_EXACT_SNAPSHOT")
    bindings = derive_feature_publication_slot_bindings(_snapshot())
    assert len(bindings) == 446
    assert [row["ordinal"] for row in bindings] == list(range(446))
    assert receipt["unresolved_plan_slot_count"] == 90
    assert receipt["missing_required_slot_count"] == 0
    assert receipt["missing_optional_slot_count"] == 63
    assert receipt["temporal_invariants_valid"] is True
    assert result.snapshot_available_at <= result.receipt_postcommit_observed_at
    assert result.receipt_postcommit_observed_at <= result.consumer_reopened_at
    assert redis_client.store[result.latest_receipt_pointer_key] == (
        result.feature_snapshot_id.encode()
    )
    assert redis_client.receipt_ttl_seconds == 600
    assert len(redis_client.store[result.receipt_key]) < 4_096


def test_snapshot_mutation_between_prepare_and_receipt_commit_fails_closed() -> None:
    redis_client = _FakeRedis()
    redis_client.before_commit = lambda client, archive_key: client.store.__setitem__(
        archive_key,
        b'{"attacker":true}',
    )

    with pytest.raises(
        FeaturePublicationReceiptIntegrityError,
        match="SNAPSHOT_CHANGED_BEFORE_RECEIPT_COMMIT",
    ):
        _publish(redis_client, _snapshot())


def test_postcommit_tamper_before_consumer_reopen_fails_closed() -> None:
    for target in ("snapshot", "receipt"):
        redis_client = _FakeRedis()

        def tamper(
            client: _FakeRedis,
            archive_key: str,
            receipt_key: str,
            selected_target: str = target,
        ) -> None:
            key = archive_key if selected_target == "snapshot" else receipt_key
            client.store[key] = client.store[key][:-1] + b"0"

        redis_client.before_reopen = tamper
        with pytest.raises(
            (
                FeaturePublicationReceiptIntegrityError,
                FeaturePublicationReceiptValidationError,
            ),
        ):
            _publish(redis_client, _snapshot())


def test_missing_postcommit_object_before_consumer_reopen_fails_closed() -> None:
    for target in ("snapshot", "receipt"):
        redis_client = _FakeRedis()

        def remove(
            client: _FakeRedis,
            archive_key: str,
            receipt_key: str,
            selected_target: str = target,
        ) -> None:
            del client.store[archive_key if selected_target == "snapshot" else receipt_key]

        redis_client.before_reopen = remove
        expected = "SNAPSHOT_ARCHIVE_MISSING" if target == "snapshot" else "RECEIPT_MISSING"
        with pytest.raises(FeaturePublicationReceiptIntegrityError, match=expected):
            _publish(redis_client, _snapshot())


def test_redis_clock_regression_fails_closed() -> None:
    redis_client = _FakeRedis()
    calls = 0

    def regressing_time() -> tuple[str, str]:
        nonlocal calls
        calls += 1
        timestamp = _START_US + (2_000 if calls == 1 else -calls * 1_000)
        return str(timestamp // 1_000_000), str(timestamp % 1_000_000)

    redis_client._time = regressing_time  # type: ignore[method-assign]
    with pytest.raises(
        FeaturePublicationReceiptIntegrityError,
        match="POSTCOMMIT_CLOCK_ORDER_INVALID",
    ):
        _publish(redis_client, _snapshot())


def test_stale_snapshot_is_receipted_for_audit_without_becoming_authority() -> None:
    result = _publish(_FakeRedis(), _snapshot(stale=True))

    assert result.receipt["temporal_invariants_valid"] is False
    assert result.receipt["publication_binding_authenticated"] is True
    assert result.receipt["source_scope_complete"] is False
    assert result.receipt["trainer_admission_authorized"] is False


def test_missing_required_slot_is_explicit_and_cannot_be_zero_filled() -> None:
    payload = _snapshot(missing_required=True)
    result = _publish(_FakeRedis(), payload)
    missing = [
        row
        for row in derive_feature_publication_slot_bindings(payload)
        if row["value_status"] == "MISSING_REQUIRED_VALUE_HELD"
    ]

    assert result.receipt["missing_required_slot_count"] == 1
    assert len(missing) == 1
    assert missing[0]["published_value_float32_be_hex"] is None
    assert missing[0]["upstream_source_receipt_verified"] is False
    assert result.receipt["trainer_admission_authorized"] is False


def test_optional_source_presence_cannot_substitute_for_required_source_receipts() -> None:
    snapshot = json.loads(_snapshot())
    optional_slot = next(
        slot
        for slot in FEATURE_SOURCE_REGISTRY_V4.slots
        if slot.requirement_class != REQUIREMENT_REQUIRED
    )
    snapshot["features"][optional_slot.feature_name] = 999.0
    snapshot.pop("feature_snapshot_id")
    snapshot["feature_snapshot_id"] = (
        "v2_fsnap_" + hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    )

    payload = json.dumps(snapshot)
    result = _publish(_FakeRedis(), payload)

    row = derive_feature_publication_slot_bindings(payload)[optional_slot.ordinal]
    assert row["value_status"] == "PRESENT_FINITE_VALUE_BOUND"
    assert row["upstream_source_receipt_verified"] is False
    assert result.receipt["source_scope_complete"] is False
    assert result.receipt["trainer_admission_authorized"] is False


def test_constructor_and_snapshot_self_promotion_are_rejected() -> None:
    with pytest.raises(
        FeaturePublicationReceiptValidationError,
        match="FACTORY_CONSTRUCTION_REQUIRED",
    ):
        VerifiedFeaturePublication(
            feature_snapshot_id="v2_fsnap_" + "0" * 64,
            snapshot_archive_key="v2:features:snapshot:x",
            receipt_key="v2:features:publication_receipt:x",
            latest_receipt_pointer_key=("v2:features:publication_receipt:latest:BTCUSDT:1m"),
            snapshot_available_at="2027-01-15T08:00:30.000000Z",
            receipt_postcommit_observed_at="2027-01-15T08:00:30.001000Z",
            consumer_reopened_at="2027-01-15T08:00:30.002000Z",
            receipt_sha256="0" * 64,
            snapshot_payload_sha256="0" * 64,
            slot_count=446,
            complete_slot_coverage=True,
            publication_binding_authenticated=True,
            source_scope_complete=False,
            per_field_source_receipts_complete=False,
            trainer_admission_authorized=False,
            prediction_authorized=False,
            paper_trading_authorized=False,
            live_execution_authorized=False,
            receipt={},
            _construction_token=object(),
        )

    promoted = json.loads(_snapshot())
    promoted["trainer_consumable"] = True
    promoted.pop("feature_snapshot_id")
    promoted["feature_snapshot_id"] = (
        "v2_fsnap_" + hashlib.sha256(json.dumps(promoted, sort_keys=True).encode()).hexdigest()
    )
    with pytest.raises(
        FeaturePublicationReceiptValidationError,
        match="SNAPSHOT_HOLD_REQUIRED",
    ):
        _publish(_FakeRedis(), json.dumps(promoted))
