from __future__ import annotations

import copy
import hashlib
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer import (
    durable_feature_snapshot_ledger as ledger_module,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FEATURE_REQUIREMENT_POLICY_ID,
    LEGACY_INELIGIBILITY_REASON,
    MAX_APPEND_ROWS,
    MAX_FEATURE_SLOTS,
    MAX_QUERY_ROWS,
    MAX_SOURCE_RECEIPTS,
    MISSING_FEATURE_INELIGIBILITY_REASON,
    PROVENANCE_CANONICAL_V3,
    PROVENANCE_LEGACY_V1_IMPORT,
    STALE_FEATURE_INELIGIBILITY_REASON,
    DurableFeatureSnapshotLedger,
    FeatureSnapshotIdentityConflictError,
    FeatureSnapshotLedgerError,
    FeatureSnapshotReadbackError,
    FeatureSnapshotValidationError,
    FeatureSnapshotWriterLease,
    FeatureSnapshotWriterLeaseError,
    build_feature_snapshot_record,
    build_source_read_receipt,
    feature_abi_sha256,
    validate_feature_snapshot_record,
)


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


BASE = datetime(2025, 1, 1, tzinfo=UTC)


def _source_receipt(
    label: str,
    *,
    offset_seconds: int = 0,
    consumer_observed_at: str | None = None,
) -> dict[str, object]:
    event = BASE + timedelta(seconds=offset_seconds)
    available = event + timedelta(milliseconds=100)
    observed = event + timedelta(milliseconds=200)
    cutoff = event + timedelta(milliseconds=300)
    return build_source_read_receipt(
        source_label=label,
        payload_type="CANONICAL_JSON_SOURCE_PAYLOAD",
        payload_sha256=("a" if label == "closed_5m" else "b") * 64,
        payload_byte_count=128,
        event_time=_utc(event),
        available_at=_utc(available),
        consumer_observed_at=consumer_observed_at or _utc(observed),
        feature_cutoff=_utc(cutoff),
        read_locator_type="SQLITE_IMMUTABLE_ROW",
        read_locator=f"fixture.sqlite3/source/{label}/{offset_seconds}",
        read_locator_version=f"row:{label}:{offset_seconds}",
        finality_type=("CLOSED_INTERVAL" if label == "closed_5m" else "VERSIONED_SNAPSHOT"),
        finality_cutoff=_utc(event + timedelta(milliseconds=50)),
        finality_verified_at=_utc(event + timedelta(milliseconds=150)),
        finality_verifier="unit-test-finality-gate",
    )


def _record(
    *,
    original_tensor_id: str = "tensor:1",
    value_shift: float = 0.0,
    provenance: str = PROVENANCE_CANONICAL_V3,
    legacy_id: str | None = None,
    source_labels: list[str] | None = None,
    receipts: list[dict[str, object]] | None = None,
    availability: list[int] | None = None,
    feature_names: list[str] | None = None,
    values: list[float] | None = None,
    missing_mask: list[int] | None = None,
    stale_mask: list[int] | None = None,
    feature_cutoff: str | None = None,
    masa_feature_cutoff: str | None = None,
    ppo_feature_cutoff: str | None = None,
    ppo_decision_time: str | None = None,
    generated_at: str | None = None,
) -> dict[str, object]:
    labels = source_labels or ["closed_5m", "orderbook"]
    source_receipts = (
        receipts if receipts is not None else [_source_receipt(label) for label in labels]
    )
    names = feature_names or ["return_5m", "spread_bps", "volume_z"]
    feature_values = values if values is not None else [0.01 + value_shift, 2.0, -0.25]
    feature_sources = [labels[index % len(labels)] for index in range(len(names))]
    if availability is None:
        slot_missing = list(missing_mask) if missing_mask is not None else [0] * len(names)
        slot_availability = [1 - missing for missing in slot_missing]
    else:
        slot_availability = [
            availability[index % len(availability)] for index in range(len(names))
        ]
        slot_missing = (
            list(missing_mask)
            if missing_mask is not None
            else [1 - available for available in slot_availability]
        )
        if missing_mask is not None:
            slot_availability = [1 - missing for missing in slot_missing]
    feature_values = [
        0.0 if slot_missing[index] else value
        for index, value in enumerate(feature_values)
    ]
    receipt_by_label = {
        str(receipt["source_label"]): receipt
        for receipt in source_receipts
        if isinstance(receipt.get("source_label"), str)
    }
    feature_bindings = [
        (
            str(receipt_by_label[source_label]["receipt_sha256"])
            if available and source_label in receipt_by_label
            else None
        )
        for source_label, available in zip(
            feature_sources,
            slot_availability,
            strict=True,
        )
    ]
    decision_time = ppo_decision_time or _utc(BASE + timedelta(seconds=2))
    return build_feature_snapshot_record(
        provenance_classification=provenance,
        legacy_v1_snapshot_id=legacy_id,
        symbol="BTCUSDT",
        timeframe="5m",
        feature_snapshot_id=f"feature_snapshot:{original_tensor_id}",
        tensor_decision_time=decision_time,
        temporal_rejection_reasons=[],
        ordered_feature_names=names,
        feature_values=feature_values,
        missing_mask=slot_missing,
        stale_mask=stale_mask if stale_mask is not None else [0] * len(names),
        source_availability_mask=slot_availability,
        ordered_feature_source_labels=feature_sources,
        feature_source_receipt_sha256s=feature_bindings,
        source_read_receipts=source_receipts,
        feature_requirement_policy_id=FEATURE_REQUIREMENT_POLICY_ID,
        ordered_feature_requirement_classes=["REQUIRED"] * len(names),
        original_tensor_id=original_tensor_id,
        source_lineage_material={
            "lineage_schema": "fixture_v1",
            "ordered_sources": labels,
            "tensor_builder": "unit-test",
        },
        feature_cutoff=feature_cutoff or _utc(BASE + timedelta(seconds=1)),
        masa_feature_cutoff=masa_feature_cutoff
        or _utc(BASE + timedelta(seconds=1, milliseconds=100)),
        ppo_feature_cutoff=ppo_feature_cutoff
        or _utc(BASE + timedelta(seconds=1, milliseconds=200)),
        ppo_decision_time=decision_time,
        generated_at=generated_at or _utc(BASE + timedelta(seconds=1, milliseconds=500)),
    )


def _builder_kwargs_from_record(record: dict[str, object]) -> dict[str, object]:
    envelope = record["frozen_envelope"]
    assert isinstance(envelope, dict)
    abi = envelope["feature_abi"]
    assert isinstance(abi, dict)
    return {
        "provenance_classification": envelope["provenance_classification"],
        "legacy_v1_snapshot_id": envelope["legacy_v1_snapshot_id"],
        "symbol": envelope["symbol"],
        "timeframe": envelope["timeframe"],
        "feature_snapshot_id": envelope["feature_snapshot_id"],
        "tensor_decision_time": envelope["tensor_decision_time"],
        "temporal_rejection_reasons": envelope["temporal_rejection_reasons"],
        "ordered_feature_names": envelope["ordered_feature_names"],
        "feature_values": envelope["feature_values"],
        "missing_mask": envelope["missing_mask"],
        "stale_mask": envelope["stale_mask"],
        "source_availability_mask": envelope["source_availability_mask"],
        "ordered_feature_source_labels": envelope[
            "ordered_feature_source_labels"
        ],
        "feature_source_receipt_sha256s": envelope[
            "feature_source_receipt_sha256s"
        ],
        "source_read_receipts": envelope["source_read_receipts"],
        "feature_requirement_policy_id": FEATURE_REQUIREMENT_POLICY_ID,
        "ordered_feature_requirement_classes": abi[
            "ordered_feature_requirement_classes"
        ],
        "original_tensor_id": envelope["original_tensor_id"],
        "source_lineage_material": envelope["source_lineage_material"],
        "feature_cutoff": envelope["feature_cutoff"],
        "masa_feature_cutoff": envelope["masa_feature_cutoff"],
        "ppo_feature_cutoff": envelope["ppo_feature_cutoff"],
        "ppo_decision_time": envelope["ppo_decision_time"],
        "generated_at": envelope["generated_at"],
    }


def _resign_record(record: dict[str, object]) -> None:
    envelope = record["frozen_envelope"]
    envelope_sha256 = ledger_module.stable_sha256(envelope)
    record["frozen_envelope_sha256"] = envelope_sha256
    record["durable_snapshot_id"] = f"feature_snapshot_v3_{envelope_sha256}"
    record["record_sha256"] = ledger_module.stable_sha256(
        {key: value for key, value in record.items() if key != "record_sha256"}
    )


def _resign_receipt(receipt: dict[str, object]) -> None:
    receipt["read_evidence_sha256"] = ledger_module.stable_sha256(receipt["read_evidence"])
    receipt["finality_evidence_sha256"] = ledger_module.stable_sha256(receipt["finality_evidence"])
    receipt["receipt_sha256"] = ledger_module.stable_sha256(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )


def _ledger(tmp_path: Path) -> DurableFeatureSnapshotLedger:
    return DurableFeatureSnapshotLedger(tmp_path / "feature-snapshots.sqlite3")


def test_append_is_deterministically_idempotent_and_conflicts_fail_closed(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    record = _record()

    first = ledger.append_snapshot(record)
    second = ledger.append_snapshot(copy.deepcopy(record))

    assert first == second
    assert first.inserted_rows == 1
    assert first.duplicate_rows == 0
    assert first.transaction_readback_verified is True
    conflicting = _record(value_shift=0.5, original_tensor_id="tensor:1")
    with pytest.raises(FeatureSnapshotIdentityConflictError):
        ledger.append_snapshot(conflicting)
    assert ledger.verify_integrity_streaming().verified_records == 1


def test_mixed_duplicate_and_insert_batch_has_exact_ordered_dispositions(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    first = _record(original_tensor_id="tensor:1")
    second = _record(original_tensor_id="tensor:2", value_shift=0.2)
    ledger.append_snapshot(first)

    mixed = ledger.append_snapshots([first, second, second])

    assert mixed.attempted_rows == 3
    assert mixed.inserted_rows == 1
    assert mixed.duplicate_rows == 2
    report = ledger.verify_integrity_streaming(chunk_size=MAX_QUERY_ROWS)
    assert report.verified_records == 2
    assert report.verified_append_receipts == 2


def test_exact_path_writer_lease_is_nonblocking_and_one_shot(tmp_path: Path) -> None:
    path = (tmp_path / "ledger.sqlite3").resolve()
    first = FeatureSnapshotWriterLease.acquire(path)
    try:
        assert first.held is True
        assert first.contract()["ledger_path"] == str(path)
        with pytest.raises(FeatureSnapshotWriterLeaseError, match="already_held"):
            FeatureSnapshotWriterLease.acquire(path)
        with pytest.raises(FeatureSnapshotWriterLeaseError, match="path_mismatch"):
            first.validate_for(tmp_path / "other.sqlite3")
    finally:
        first.release()
    assert first.held is False
    with pytest.raises(FeatureSnapshotWriterLeaseError, match="not_held"):
        first.__enter__()
    with FeatureSnapshotWriterLease.acquire(path) as reacquired:
        assert reacquired.held is True


def test_writer_lease_rejects_forged_construction_and_hardlinks(tmp_path: Path) -> None:
    path = (tmp_path / "ledger.sqlite3").resolve()
    lock_path = ledger_module.feature_snapshot_writer_lease_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    lock_stat = os.fstat(descriptor)
    try:
        with pytest.raises(FeatureSnapshotWriterLeaseError, match="must_use_acquire"):
            FeatureSnapshotWriterLease(
                ledger_path=path,
                lock_path=lock_path,
                file_descriptor=descriptor,
                lock_device=lock_stat.st_dev,
                lock_inode=lock_stat.st_ino,
            )
    finally:
        os.close(descriptor)

    alias = tmp_path / "forged-hardlink.lock"
    os.link(lock_path, alias)
    try:
        with pytest.raises(FeatureSnapshotWriterLeaseError, match="hardlink_forbidden"):
            FeatureSnapshotWriterLease.acquire(path)
    finally:
        alias.unlink()

    lease = FeatureSnapshotWriterLease.acquire(path)
    alias_after_lock = tmp_path / "post-acquire-hardlink.lock"
    try:
        os.link(lock_path, alias_after_lock)
        with pytest.raises(FeatureSnapshotWriterLeaseError, match="inode_changed"):
            lease.validate_for(path)
    finally:
        lease.release()
        alias_after_lock.unlink(missing_ok=True)
    with FeatureSnapshotWriterLease.acquire(path) as reacquired:
        assert reacquired.held is True


def test_writer_lease_context_validation_failure_releases_fd_and_flock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = (tmp_path / "ledger.sqlite3").resolve()
    ledger = DurableFeatureSnapshotLedger(path)
    original_validate = FeatureSnapshotWriterLease.validate_for
    calls = 0

    def fail_context_validation(self: FeatureSnapshotWriterLease, ledger_path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise FeatureSnapshotWriterLeaseError("simulated_context_validation_failure")
        original_validate(self, ledger_path)

    fd_count_before = len(os.listdir("/proc/self/fd"))
    monkeypatch.setattr(
        FeatureSnapshotWriterLease,
        "validate_for",
        fail_context_validation,
    )
    with pytest.raises(FeatureSnapshotWriterLeaseError, match="simulated_context"):
        with ledger.writer_lease():
            pytest.fail("context must not be entered")
    monkeypatch.setattr(FeatureSnapshotWriterLease, "validate_for", original_validate)
    assert len(os.listdir("/proc/self/fd")) == fd_count_before
    with FeatureSnapshotWriterLease.acquire(path):
        pass


def test_writer_lease_acquire_validation_failure_releases_fd_and_flock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = (tmp_path / "ledger.sqlite3").resolve()
    original_validate = FeatureSnapshotWriterLease.validate_for
    fd_count_before = len(os.listdir("/proc/self/fd"))

    def fail_postlock_validation(self: FeatureSnapshotWriterLease, ledger_path: Path) -> None:
        raise FeatureSnapshotWriterLeaseError("simulated_postlock_validation_failure")

    monkeypatch.setattr(
        FeatureSnapshotWriterLease,
        "validate_for",
        fail_postlock_validation,
    )
    with pytest.raises(FeatureSnapshotWriterLeaseError, match="simulated_postlock"):
        FeatureSnapshotWriterLease.acquire(path)
    monkeypatch.setattr(FeatureSnapshotWriterLease, "validate_for", original_validate)
    assert len(os.listdir("/proc/self/fd")) == fd_count_before
    with FeatureSnapshotWriterLease.acquire(path):
        pass


def test_postcommit_crash_gap_is_ineligible_until_bounded_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _ledger(tmp_path)
    original = DurableFeatureSnapshotLedger._complete_postcommit_readback

    def crash_after_canonical_commit(*args: object, **kwargs: object) -> None:
        raise FeatureSnapshotReadbackError("simulated_postcommit_crash")

    monkeypatch.setattr(
        DurableFeatureSnapshotLedger,
        "_complete_postcommit_readback",
        crash_after_canonical_commit,
    )
    with pytest.raises(FeatureSnapshotReadbackError, match="simulated_postcommit"):
        ledger.append_snapshot(_record())
    assert (
        ledger.query_fixed_cutoff(
            decision_time_cutoff=_utc(BASE + timedelta(seconds=2)),
            training_observed_at=_utc(BASE + timedelta(days=1)),
        )
        == []
    )
    assert ledger.query_projection_outbox() == []
    monkeypatch.setattr(DurableFeatureSnapshotLedger, "_complete_postcommit_readback", original)
    recovery = ledger.recover_pending_postcommit_readbacks(max_transactions=1)
    assert recovery["recovered_transactions"] == 1
    rows = ledger.query_fixed_cutoff(
        decision_time_cutoff=_utc(BASE + timedelta(seconds=2)),
        training_observed_at=_utc(datetime.now(tz=UTC) + timedelta(minutes=1)),
    )
    assert len(rows) == 1


def test_fixed_cutoff_requires_postcommit_receipt_observable_by_training(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    result = ledger.append_snapshot(_record())

    before_postcommit = ledger.query_fixed_cutoff(
        decision_time_cutoff=_utc(BASE + timedelta(seconds=2)),
        training_observed_at=_utc(BASE + timedelta(seconds=2)),
    )
    at_postcommit = ledger.query_fixed_cutoff(
        decision_time_cutoff=_utc(BASE + timedelta(seconds=2)),
        training_observed_at=result.postcommit_readback_at,
    )

    assert before_postcommit == []
    assert len(at_postcommit) == 1
    assert at_postcommit[0].postcommit_readback_at == result.postcommit_readback_at
    with pytest.raises(
        FeatureSnapshotLedgerError,
        match="decision_time_cutoff_after_training_observed_at",
    ):
        ledger.query_fixed_cutoff(
            decision_time_cutoff=_utc(BASE + timedelta(days=2)),
            training_observed_at=_utc(BASE + timedelta(days=1)),
        )


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        (
            {
                "masa_feature_cutoff": _utc(BASE + timedelta(seconds=1.5)),
                "ppo_feature_cutoff": _utc(BASE + timedelta(seconds=1.4)),
            },
            "MASA_FEATURE_CUTOFF_AFTER_PPO_FEATURE_CUTOFF",
        ),
        (
            {
                "ppo_feature_cutoff": _utc(BASE + timedelta(seconds=3)),
                "ppo_decision_time": _utc(BASE + timedelta(seconds=2)),
            },
            "PPO_FEATURE_CUTOFF_AFTER_TENSOR_DECISION_TIME",
        ),
        (
            {
                "feature_cutoff": _utc(BASE + timedelta(seconds=2.5)),
                "ppo_decision_time": _utc(BASE + timedelta(seconds=2)),
            },
            "FEATURE_CUTOFF_AFTER_TENSOR_DECISION_TIME",
        ),
    ],
)
def test_explicit_model_clocks_never_substitute_or_cross_decision(
    override: dict[str, str], reason: str
) -> None:
    with pytest.raises(FeatureSnapshotValidationError, match=reason):
        _record(**override)


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("event_time", "SOURCE_EVENT_TIME_INVALID"),
        ("available_at", "SOURCE_AVAILABLE_AT_INVALID"),
        ("consumer_observed_at", "SOURCE_CONSUMER_OBSERVED_AT_INVALID"),
        ("feature_cutoff", "SOURCE_FEATURE_CUTOFF_INVALID"),
        ("finality_cutoff", "SOURCE_FINALITY_CUTOFF_INVALID"),
        ("finality_verified_at", "SOURCE_FINALITY_VERIFIED_AT_INVALID"),
    ],
)
@pytest.mark.parametrize(
    "extreme_clock",
    [
        "9999-12-31T23:59:59.999999-23:59",
        "0001-01-01T00:00:00.000000+23:59",
    ],
)
def test_source_receipt_extreme_offset_clocks_fail_closed(
    field: str,
    reason: str,
    extreme_clock: str,
) -> None:
    event = BASE
    kwargs = {
        "source_label": "closed_5m",
        "payload_type": "CANONICAL_JSON_SOURCE_PAYLOAD",
        "payload_sha256": "a" * 64,
        "payload_byte_count": 128,
        "event_time": _utc(event),
        "available_at": _utc(event + timedelta(milliseconds=100)),
        "consumer_observed_at": _utc(event + timedelta(milliseconds=200)),
        "feature_cutoff": _utc(event + timedelta(milliseconds=300)),
        "read_locator_type": "SQLITE_IMMUTABLE_ROW",
        "read_locator": "fixture.sqlite3/source/closed_5m/extreme-clock",
        "read_locator_version": "row:closed_5m:extreme-clock",
        "finality_type": "CLOSED_INTERVAL",
        "finality_cutoff": _utc(event + timedelta(milliseconds=50)),
        "finality_verified_at": _utc(event + timedelta(milliseconds=150)),
        "finality_verifier": "unit-test-finality-gate",
    }
    kwargs[field] = extreme_clock

    with pytest.raises(FeatureSnapshotValidationError, match=reason) as captured:
        build_source_read_receipt(**kwargs)

    assert "date value out of range" not in str(captured.value)


@pytest.mark.parametrize("numeric_base", [int, float])
def test_tensor_numeric_subclasses_never_execute_conversion_hooks(
    numeric_base: type[int] | type[float],
) -> None:
    conversion_called = False

    class HostileNumeric(numeric_base):  # type: ignore[misc, valid-type]
        def __float__(self) -> float:
            nonlocal conversion_called
            conversion_called = True
            raise RuntimeError("ATTACKER_SECRET_NUMERIC_CONVERSION")

    hostile = HostileNumeric(1)
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="FEATURE_VALUES_NOT_FINITE_FLOAT32",
    ) as captured:
        _record(values=[hostile, 2.0, -0.25])

    assert conversion_called is False
    assert "ATTACKER_SECRET_NUMERIC_CONVERSION" not in str(captured.value)


def test_feature_abi_name_sequences_fail_before_caller_hooks() -> None:
    hooks_called: list[str] = []

    class HostileNames(list[str]):
        def __len__(self) -> int:
            hooks_called.append("len")
            raise RuntimeError("ATTACKER_SECRET_ABI_NAMES_LEN")

        def __iter__(self):  # type: ignore[no-untyped-def]
            hooks_called.append("iter")
            raise RuntimeError("ATTACKER_SECRET_ABI_NAMES_ITER")

    hostile_names = HostileNames(["last_price"])
    for builder in (
        ledger_module.feature_requirement_classes_for_names,
        ledger_module.feature_abi_contract,
    ):
        with pytest.raises(
            FeatureSnapshotValidationError,
            match="ORDERED_FEATURE_NAMES_NOT_SEQUENCE",
        ) as captured:
            builder(hostile_names)
        assert "ATTACKER_SECRET_ABI_NAMES" not in str(captured.value)

    assert hooks_called == []


def test_feature_abi_names_fail_before_hash_or_equality_hooks() -> None:
    hooks_called: list[str] = []

    class HostileFeatureName(str):
        def __hash__(self) -> int:
            hooks_called.append("hash")
            raise RuntimeError("ATTACKER_SECRET_ABI_NAME_HASH")

        def __eq__(self, other: object) -> bool:
            hooks_called.append("eq")
            raise RuntimeError("ATTACKER_SECRET_ABI_NAME_EQ")

    hostile_name = HostileFeatureName("last_price")
    for builder in (
        ledger_module.feature_requirement_classes_for_names,
        ledger_module.feature_abi_contract,
    ):
        with pytest.raises(
            FeatureSnapshotValidationError,
            match="FEATURE_NAME_INVALID",
        ) as captured:
            builder([hostile_name])
        assert "ATTACKER_SECRET_ABI_NAME" not in str(captured.value)

    assert hooks_called == []


def test_feature_abi_policy_and_requirements_fail_before_caller_hooks() -> None:
    policy_hooks: list[str] = []
    requirement_hooks: list[str] = []
    sequence_hooks: list[str] = []

    class HostilePolicy(str):
        def __eq__(self, other: object) -> bool:
            policy_hooks.append("eq")
            raise RuntimeError("ATTACKER_SECRET_ABI_POLICY_EQ")

    class HostileRequirement(str):
        def __hash__(self) -> int:
            requirement_hooks.append("hash")
            raise RuntimeError("ATTACKER_SECRET_ABI_REQUIREMENT_HASH")

        def __eq__(self, other: object) -> bool:
            requirement_hooks.append("eq")
            raise RuntimeError("ATTACKER_SECRET_ABI_REQUIREMENT_EQ")

    class HostileRequirements(list[str]):
        def __len__(self) -> int:
            sequence_hooks.append("len")
            raise RuntimeError("ATTACKER_SECRET_ABI_REQUIREMENTS_LEN")

        def __iter__(self):  # type: ignore[no-untyped-def]
            sequence_hooks.append("iter")
            raise RuntimeError("ATTACKER_SECRET_ABI_REQUIREMENTS_ITER")

    with pytest.raises(
        FeatureSnapshotValidationError,
        match="FEATURE_REQUIREMENT_POLICY_ID_MISMATCH",
    ) as policy_error:
        ledger_module.feature_abi_contract(
            ["last_price"],
            feature_requirement_policy_id=HostilePolicy(
                FEATURE_REQUIREMENT_POLICY_ID
            ),
        )
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="FEATURE_REQUIREMENT_CLASS_INVALID",
    ) as requirement_error:
        ledger_module.feature_abi_contract(
            ["last_price"],
            ordered_feature_requirement_classes=[HostileRequirement("REQUIRED")],
        )
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="ORDERED_FEATURE_REQUIREMENT_CLASSES_NOT_SEQUENCE",
    ) as sequence_error:
        ledger_module.feature_abi_contract(
            ["last_price"],
            ordered_feature_requirement_classes=HostileRequirements(["REQUIRED"]),
        )

    assert policy_hooks == []
    assert requirement_hooks == []
    assert sequence_hooks == []
    combined_errors = " ".join(
        (str(policy_error.value), str(requirement_error.value), str(sequence_error.value))
    )
    assert "ATTACKER_SECRET_ABI" not in combined_errors


def _source_receipt_builder_kwargs() -> dict[str, object]:
    return {
        "source_label": "closed_5m",
        "payload_type": "CANONICAL_JSON_SOURCE_PAYLOAD",
        "payload_sha256": "a" * 64,
        "payload_byte_count": 128,
        "event_time": _utc(BASE),
        "available_at": _utc(BASE + timedelta(milliseconds=100)),
        "consumer_observed_at": _utc(BASE + timedelta(milliseconds=200)),
        "feature_cutoff": _utc(BASE + timedelta(milliseconds=300)),
        "read_locator_type": "SQLITE_IMMUTABLE_ROW",
        "read_locator": "fixture.sqlite3/source/closed_5m/type-boundary",
        "read_locator_version": "row:closed_5m:type-boundary",
        "finality_type": "CLOSED_INTERVAL",
        "finality_cutoff": _utc(BASE + timedelta(milliseconds=50)),
        "finality_verified_at": _utc(BASE + timedelta(milliseconds=150)),
        "finality_verifier": "unit-test-finality-gate",
        "receipt_kind": "DIRECT_READ",
    }


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("receipt_kind", "SOURCE_RECEIPT_KIND_INVALID"),
        ("read_locator_type", "SOURCE_READ_EVIDENCE_LOCATOR_TYPE_INVALID"),
        ("finality_type", "SOURCE_FINALITY_EVIDENCE_TYPE_INVALID"),
    ],
)
@pytest.mark.parametrize(
    "invalid_value",
    [
        ["ATTACKER_SECRET_JSON_ENUM"],
        {"ATTACKER_SECRET_JSON_ENUM": True},
    ],
    ids=["list", "dict"],
)
def test_source_receipt_enum_objects_return_fixed_validation_errors(
    field: str,
    reason: str,
    invalid_value: object,
) -> None:
    kwargs = _source_receipt_builder_kwargs()
    kwargs[field] = invalid_value

    with pytest.raises(FeatureSnapshotValidationError, match=reason) as captured:
        build_source_read_receipt(**kwargs)  # type: ignore[arg-type]

    assert "unhashable type" not in str(captured.value)
    assert "ATTACKER_SECRET_JSON_ENUM" not in str(captured.value)


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("receipt_kind", "SOURCE_RECEIPT_KIND_INVALID"),
        ("read_locator_type", "SOURCE_READ_EVIDENCE_LOCATOR_TYPE_INVALID"),
        ("finality_type", "SOURCE_FINALITY_EVIDENCE_TYPE_INVALID"),
    ],
)
def test_source_receipt_enum_subclasses_fail_before_caller_hooks(
    field: str,
    reason: str,
) -> None:
    hooks_called: list[str] = []

    class HostileEnum(str):
        def __hash__(self) -> int:
            hooks_called.append("hash")
            raise RuntimeError("ATTACKER_SECRET_SOURCE_ENUM_HASH")

        def __eq__(self, other: object) -> bool:
            hooks_called.append("eq")
            raise RuntimeError("ATTACKER_SECRET_SOURCE_ENUM_EQ")

    kwargs = _source_receipt_builder_kwargs()
    kwargs[field] = HostileEnum(str(kwargs[field]))
    with pytest.raises(FeatureSnapshotValidationError, match=reason) as captured:
        build_source_read_receipt(**kwargs)  # type: ignore[arg-type]

    assert hooks_called == []
    assert "ATTACKER_SECRET_SOURCE_ENUM" not in str(captured.value)


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("feature_values", "FEATURE_VALUES_NOT_SEQUENCE"),
        ("missing_mask", "MISSING_MASK_NOT_SEQUENCE"),
        ("source_read_receipts", "SOURCE_READ_RECEIPTS_NOT_SEQUENCE"),
        (
            "temporal_rejection_reasons",
            "TEMPORAL_REJECTION_REASONS_NOT_SEQUENCE",
        ),
    ],
)
def test_builder_sequence_subclasses_never_execute_length_hooks(
    field: str,
    reason: str,
) -> None:
    kwargs = _builder_kwargs_from_record(_record())
    length_called = False

    class HostileSequence(list[object]):
        def __len__(self) -> int:
            nonlocal length_called
            length_called = True
            raise RuntimeError("ATTACKER_SECRET_SEQUENCE_LENGTH")

    original = kwargs[field]
    assert isinstance(original, list)
    kwargs[field] = HostileSequence(original)

    with pytest.raises(FeatureSnapshotValidationError, match=reason) as captured:
        build_feature_snapshot_record(**kwargs)  # type: ignore[arg-type]

    assert length_called is False
    assert "ATTACKER_SECRET_SEQUENCE_LENGTH" not in str(captured.value)


def test_builder_temporal_reasons_never_execute_string_hooks() -> None:
    kwargs = _builder_kwargs_from_record(_record())
    string_called = False

    class HostileReason:
        def __str__(self) -> str:
            nonlocal string_called
            string_called = True
            raise RuntimeError("ATTACKER_SECRET_TEMPORAL_REASON")

    kwargs["temporal_rejection_reasons"] = [HostileReason()]
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="TEMPORAL_REJECTION_REASON_INVALID",
    ) as captured:
        build_feature_snapshot_record(**kwargs)  # type: ignore[arg-type]

    assert string_called is False
    assert "ATTACKER_SECRET_TEMPORAL_REASON" not in str(captured.value)


def test_builder_nested_lineage_never_observes_hostile_class_metadata() -> None:
    kwargs = _builder_kwargs_from_record(_record())
    class_observed = False

    class HostileLineageValue:
        @property
        def __class__(self) -> type[object]:
            nonlocal class_observed
            class_observed = True
            raise RuntimeError("ATTACKER_SECRET_LINEAGE_CLASS")

    lineage = dict(kwargs["source_lineage_material"])  # type: ignore[arg-type]
    lineage["hostile_nested_value"] = HostileLineageValue()
    kwargs["source_lineage_material"] = lineage

    with pytest.raises(
        FeatureSnapshotValidationError,
        match="STRICT_JSON_UNSUPPORTED_TYPE",
    ) as captured:
        build_feature_snapshot_record(**kwargs)  # type: ignore[arg-type]

    assert class_observed is False
    assert "ATTACKER_SECRET_LINEAGE_CLASS" not in str(captured.value)


def test_builder_mask_values_never_observe_hostile_class_metadata() -> None:
    kwargs = _builder_kwargs_from_record(_record())
    class_observed = False

    class HostileMaskValue:
        @property
        def __class__(self) -> type[object]:
            nonlocal class_observed
            class_observed = True
            raise RuntimeError("ATTACKER_SECRET_MASK_CLASS")

    kwargs["missing_mask"] = [HostileMaskValue(), 0, 0]
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="MISSING_MASK_NOT_BINARY",
    ) as captured:
        build_feature_snapshot_record(**kwargs)  # type: ignore[arg-type]

    assert class_observed is False
    assert "ATTACKER_SECRET_MASK_CLASS" not in str(captured.value)


def test_record_validator_stops_before_hostile_mapping_hooks() -> None:
    hooks_called: list[str] = []

    class HostileRecord(dict[str, object]):
        def __iter__(self):  # type: ignore[no-untyped-def]
            hooks_called.append("iter")
            raise RuntimeError("ATTACKER_SECRET_RECORD_ITER")

        def __len__(self) -> int:
            hooks_called.append("len")
            raise RuntimeError("ATTACKER_SECRET_RECORD_LEN")

        def get(self, *_: object, **__: object) -> object:
            hooks_called.append("get")
            raise RuntimeError("ATTACKER_SECRET_RECORD_GET")

        def items(self):  # type: ignore[no-untyped-def]
            hooks_called.append("items")
            raise RuntimeError("ATTACKER_SECRET_RECORD_ITEMS")

    hostile = HostileRecord(_record())
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="STRICT_JSON_UNSUPPORTED_TYPE",
    ) as captured:
        validate_feature_snapshot_record(hostile)

    assert hooks_called == []
    assert "ATTACKER_SECRET_RECORD" not in str(captured.value)


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("provenance", "PROVENANCE_CLASSIFICATION_INVALID"),
        ("requirement", "FEATURE_REQUIREMENT_CLASS_INVALID"),
        ("receipt_kind", "SOURCE_RECEIPT_KIND_INVALID"),
        ("read_locator_type", "SOURCE_READ_EVIDENCE_LOCATOR_TYPE_INVALID"),
        ("finality_type", "SOURCE_FINALITY_EVIDENCE_TYPE_INVALID"),
    ],
)
@pytest.mark.parametrize(
    "invalid_value",
    [
        ["ATTACKER_SECRET_JSON_ENUM"],
        {"ATTACKER_SECRET_JSON_ENUM": True},
    ],
    ids=["list", "dict"],
)
def test_record_validator_enum_objects_return_fixed_validation_errors(
    field: str,
    reason: str,
    invalid_value: object,
) -> None:
    record = copy.deepcopy(_record())
    envelope = record["frozen_envelope"]
    assert isinstance(envelope, dict)
    value = copy.deepcopy(invalid_value)
    if field == "provenance":
        envelope["provenance_classification"] = value
    elif field == "requirement":
        abi = envelope["feature_abi"]
        assert isinstance(abi, dict)
        abi["ordered_feature_requirement_classes"] = [value, "REQUIRED", "REQUIRED"]
    else:
        receipts = envelope["source_read_receipts"]
        assert isinstance(receipts, list)
        receipt = receipts[0]
        assert isinstance(receipt, dict)
        if field == "receipt_kind":
            receipt["receipt_kind"] = value
        elif field == "read_locator_type":
            read_evidence = receipt["read_evidence"]
            assert isinstance(read_evidence, dict)
            read_evidence["read_locator_type"] = value
        else:
            finality_evidence = receipt["finality_evidence"]
            assert isinstance(finality_evidence, dict)
            finality_evidence["finality_type"] = value

    with pytest.raises(FeatureSnapshotValidationError, match=reason) as captured:
        validate_feature_snapshot_record(record)

    assert "unhashable type" not in str(captured.value)
    assert "ATTACKER_SECRET_JSON_ENUM" not in str(captured.value)


def test_record_validator_nested_string_subclass_fails_before_caller_hooks() -> None:
    hooks_called: list[str] = []

    class HostileProvenance(str):
        def __hash__(self) -> int:
            hooks_called.append("hash")
            raise RuntimeError("ATTACKER_SECRET_RECORD_PROVENANCE_HASH")

        def __eq__(self, other: object) -> bool:
            hooks_called.append("eq")
            raise RuntimeError("ATTACKER_SECRET_RECORD_PROVENANCE_EQ")

    record = _record()
    envelope = record["frozen_envelope"]
    assert isinstance(envelope, dict)
    envelope["provenance_classification"] = HostileProvenance(
        PROVENANCE_CANONICAL_V3
    )
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="STRICT_JSON_UNSUPPORTED_TYPE",
    ) as captured:
        validate_feature_snapshot_record(record)

    assert hooks_called == []
    assert "ATTACKER_SECRET_RECORD_PROVENANCE" not in str(captured.value)


@pytest.mark.parametrize(
    "invalid_value",
    [
        ["ATTACKER_SECRET_JSON_ENUM"],
        {"ATTACKER_SECRET_JSON_ENUM": True},
    ],
    ids=["list", "dict"],
)
def test_persisted_receipt_enum_objects_fail_with_fixed_readback_errors(
    tmp_path: Path,
    invalid_value: object,
) -> None:
    ledger = _ledger(tmp_path)
    ledger.append_snapshot(_record())
    connection = sqlite3.connect(ledger.path)
    connection.row_factory = sqlite3.Row
    try:
        append_row = dict(
            connection.execute(
                "SELECT * FROM feature_snapshot_append_receipts"
            ).fetchone()
        )
        projection_row = dict(
            connection.execute(
                "SELECT * FROM feature_snapshot_projection_outbox"
            ).fetchone()
        )
    finally:
        connection.close()

    append_material = ledger_module.json.loads(append_row["receipt_json"])
    append_material["attempted_dispositions"] = [copy.deepcopy(invalid_value)]
    append_row["receipt_json"] = ledger_module.canonical_json(append_material)
    with pytest.raises(
        FeatureSnapshotReadbackError,
        match="APPEND_RECEIPT_ATTEMPTED_DISPOSITIONS_INVALID",
    ) as append_error:
        ledger_module.DurableFeatureSnapshotLedger._validated_append_receipt_row(
            append_row  # type: ignore[arg-type]
        )

    projection_material = ledger_module.json.loads(projection_row["projection_json"])
    projection_material["provenance_classification"] = copy.deepcopy(invalid_value)
    projection_row["projection_json"] = ledger_module.canonical_json(
        projection_material
    )
    with pytest.raises(
        FeatureSnapshotReadbackError,
        match="PROJECTION_OUTBOX_PROVENANCE_INVALID",
    ) as projection_error:
        ledger_module.DurableFeatureSnapshotLedger._validated_projection_row(
            projection_row  # type: ignore[arg-type]
        )

    combined_errors = f"{append_error.value} {projection_error.value}"
    assert "unhashable type" not in combined_errors
    assert "ATTACKER_SECRET_JSON_ENUM" not in combined_errors


def test_source_event_availability_observation_and_cutoff_must_precede_decision() -> None:
    future_observation = _utc(BASE + timedelta(seconds=3))
    receipt = _source_receipt("closed_5m", consumer_observed_at=future_observation)
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="SOURCE_CONSUMER_OBSERVED_AT_AFTER_TENSOR_DECISION_TIME",
    ):
        _record(
            source_labels=["closed_5m"],
            receipts=[receipt],
            availability=[1],
        )

    invalid = copy.deepcopy(_source_receipt("closed_5m"))
    invalid["available_at"] = _utc(BASE - timedelta(seconds=1))
    with pytest.raises(
        FeatureSnapshotValidationError, match="SOURCE_EVENT_TIME_AFTER_AVAILABLE_AT"
    ):
        tampered = _record(
            source_labels=["closed_5m"],
            receipts=[_source_receipt("closed_5m")],
            availability=[1],
        )
        tampered["frozen_envelope"]["source_read_receipts"] = [invalid]
        validate_feature_snapshot_record(tampered)


def test_generated_at_is_mandatory_canonical_and_after_every_source_read() -> None:
    missing = copy.deepcopy(_record())
    missing["frozen_envelope"].pop("generated_at")
    _resign_record(missing)
    with pytest.raises(FeatureSnapshotValidationError, match="GENERATED_AT_INVALID"):
        validate_feature_snapshot_record(missing)

    noncanonical = copy.deepcopy(_record())
    noncanonical["frozen_envelope"]["generated_at"] = "2025-01-01T00:00:01.500000+00:00"
    _resign_record(noncanonical)
    with pytest.raises(FeatureSnapshotValidationError, match="GENERATED_AT_NOT_CANONICAL"):
        validate_feature_snapshot_record(noncanonical)

    with pytest.raises(
        FeatureSnapshotValidationError,
        match="GENERATED_AT_BEFORE_SOURCE_CONSUMER_OBSERVED_AT",
    ):
        _record(generated_at=_utc(BASE + timedelta(milliseconds=150)))


def test_source_receipt_exact_typed_read_and_finality_bindings_fail_closed() -> None:
    payload_mismatch = copy.deepcopy(_source_receipt("closed_5m"))
    payload_mismatch["read_evidence"]["payload_sha256"] = "c" * 64
    payload_mismatch["read_evidence_sha256"] = ledger_module.stable_sha256(
        payload_mismatch["read_evidence"]
    )
    payload_mismatch["finality_evidence"]["read_evidence_sha256"] = payload_mismatch[
        "read_evidence_sha256"
    ]
    _resign_receipt(payload_mismatch)
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="SOURCE_READ_EVIDENCE_PAYLOAD_BINDING_MISMATCH",
    ):
        _record(
            source_labels=["closed_5m"],
            receipts=[payload_mismatch],
            availability=[1],
        )

    locator_mismatch = copy.deepcopy(_source_receipt("closed_5m"))
    locator_mismatch["read_evidence"]["read_locator"] = "other.sqlite3/row/99"
    locator_mismatch["read_evidence_sha256"] = ledger_module.stable_sha256(
        locator_mismatch["read_evidence"]
    )
    locator_mismatch["finality_evidence"]["read_evidence_sha256"] = locator_mismatch[
        "read_evidence_sha256"
    ]
    _resign_receipt(locator_mismatch)
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="SOURCE_READ_EVIDENCE_LOCATOR_SHA256_MISMATCH",
    ):
        _record(
            source_labels=["closed_5m"],
            receipts=[locator_mismatch],
            availability=[1],
        )

    unfinished = copy.deepcopy(_source_receipt("closed_5m"))
    unfinished["finality_evidence"]["event_final"] = False
    _resign_receipt(unfinished)
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="SOURCE_FINALITY_EVIDENCE_NOT_FINAL",
    ):
        _record(
            source_labels=["closed_5m"],
            receipts=[unfinished],
            availability=[1],
        )

    extra_field = copy.deepcopy(_source_receipt("closed_5m"))
    extra_field["finality_evidence"]["untyped_claim"] = True
    _resign_receipt(extra_field)
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="SOURCE_FINALITY_EVIDENCE_FIELD_SET_MISMATCH",
    ):
        _record(
            source_labels=["closed_5m"],
            receipts=[extra_field],
            availability=[1],
        )

    premature_availability = copy.deepcopy(_source_receipt("closed_5m"))
    premature_availability["finality_evidence"]["finality_cutoff"] = _utc(
        BASE + timedelta(milliseconds=250)
    )
    _resign_receipt(premature_availability)
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="SOURCE_FINALITY_CUTOFF_AFTER_AVAILABLE_AT",
    ):
        _record(
            source_labels=["closed_5m"],
            receipts=[premature_availability],
            availability=[1],
        )


def test_feature_tensor_abi_is_exact_and_values_are_canonical_runtime_float32() -> None:
    record = _record(values=[0.1, 2.0, -0.25])
    envelope = record["frozen_envelope"]
    assert envelope["feature_values"][0] != 0.1
    assert envelope["feature_abi"]["feature_values"] == {
        "dtype": "float32",
        "encoding": "IEEE754_BINARY32_CANONICAL_JSON_DECIMAL",
        "rank": 1,
        "shape": [3],
        "slot_layout": "ORDERED_FEATURE_NAMES",
    }
    assert envelope["feature_abi"]["source_availability_mask"]["shape"] == [3]

    for invalid in (1e100, 1e-100):
        with pytest.raises(
            FeatureSnapshotValidationError,
            match="FEATURE_VALUES_NOT_FINITE_FLOAT32",
        ):
            _record(values=[invalid, 1.0, 2.0])

    for noncanonical_value in (0.1, 1, -0.0):
        noncanonical = copy.deepcopy(record)
        noncanonical["frozen_envelope"]["feature_values"][0] = noncanonical_value
        _resign_record(noncanonical)
        with pytest.raises(
            FeatureSnapshotValidationError,
            match="FEATURE_VALUES_NOT_CANONICAL_FLOAT32",
        ):
            validate_feature_snapshot_record(noncanonical)

    forged_abi = copy.deepcopy(record)
    forged_abi["frozen_envelope"]["feature_abi"]["feature_values"]["dtype"] = "float64"
    forged_abi["frozen_envelope"]["feature_abi_sha256"] = ledger_module.stable_sha256(
        forged_abi["frozen_envelope"]["feature_abi"]
    )
    _resign_record(forged_abi)
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="FEATURE_ABI_CONTRACT_MISMATCH",
    ):
        validate_feature_snapshot_record(forged_abi)


def test_future_ppo_decision_cannot_be_archived_before_it_occurs(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    future = _record(ppo_decision_time=_utc(datetime.now(tz=UTC) + timedelta(days=1)))

    with pytest.raises(
        FeatureSnapshotValidationError,
        match="PPO_DECISION_TIME_AFTER_LEDGER_COMMIT_PREPARATION",
    ):
        ledger.append_snapshot(future)


def test_feature_and_source_order_are_frozen_into_identity() -> None:
    original = _record()
    reordered_features = _record(
        original_tensor_id="tensor:2",
        feature_names=["spread_bps", "return_5m", "volume_z"],
        values=[2.0, 0.01, -0.25],
    )
    reordered_sources = _record(
        original_tensor_id="tensor:3",
        source_labels=["orderbook", "closed_5m"],
        receipts=[_source_receipt("orderbook"), _source_receipt("closed_5m")],
    )

    assert original["durable_snapshot_id"] != reordered_features["durable_snapshot_id"]
    assert original["durable_snapshot_id"] != reordered_sources["durable_snapshot_id"]
    assert (
        original["frozen_envelope"]["feature_abi_sha256"]
        != reordered_features["frozen_envelope"]["feature_abi_sha256"]
    )

    mismatched = copy.deepcopy(original)
    source_labels = mismatched["frozen_envelope"]["ordered_feature_source_labels"]
    source_labels[0], source_labels[1] = source_labels[1], source_labels[0]
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="FEATURE_SOURCE_RECEIPT_LABEL_MISMATCH|FEATURE_SOURCE_BINDINGS_SHA256_MISMATCH",
    ):
        validate_feature_snapshot_record(mismatched)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda record: record["frozen_envelope"]["feature_values"].__setitem__(0, 99.0),
        lambda record: record["frozen_envelope"].__setitem__("feature_abi_sha256", "0" * 64),
        lambda record: record["frozen_envelope"]["source_lineage_material"].__setitem__(
            "tensor_builder", "tampered"
        ),
        lambda record: record.__setitem__("record_sha256", "0" * 64),
        lambda record: record.__setitem__("durable_snapshot_id", f"feature_snapshot_v3_{'0' * 64}"),
    ],
)
def test_tensor_abi_lineage_and_hash_tampering_is_rejected(mutation: object) -> None:
    record = copy.deepcopy(_record())
    mutation(record)  # type: ignore[operator]
    with pytest.raises(FeatureSnapshotValidationError):
        validate_feature_snapshot_record(record)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("missing_mask", [0, 0], "MISSING_MASK_DIMENSION_MISMATCH"),
        ("stale_mask", [0, 2, 0], "STALE_MASK_NOT_BINARY"),
        (
            "source_availability_mask",
            [1],
            "SOURCE_AVAILABILITY_MASK_DIMENSION_MISMATCH",
        ),
    ],
)
def test_binary_masks_are_dimensionally_aligned(field: str, value: list[int], reason: str) -> None:
    record = copy.deepcopy(_record())
    record["frozen_envelope"][field] = value
    with pytest.raises(FeatureSnapshotValidationError, match=reason):
        validate_feature_snapshot_record(record)


def test_every_available_source_requires_exact_receipt_and_unavailable_has_none() -> None:
    valid = _record(
        source_labels=["closed_5m", "orderbook"],
        receipts=[_source_receipt("closed_5m")],
        availability=[1, 0],
    )
    validated = validate_feature_snapshot_record(valid)
    assert validated["strict_training_eligible"] == 0
    assert valid["frozen_envelope"]["strict_training_ineligibility_reasons"] == [
        MISSING_FEATURE_INELIGIBILITY_REASON
    ]

    record = copy.deepcopy(valid)
    record["frozen_envelope"]["source_availability_mask"] = [1, 1, 1]
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="SOURCE_AVAILABILITY_MISSING_MASK_MISMATCH|PRESENT_FEATURE_SOURCE_RECEIPT_MISSING",
    ):
        validate_feature_snapshot_record(record)


def test_missing_and_stale_canonical_rows_are_audited_but_never_queried(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    missing = _record(
        original_tensor_id="tensor:missing",
        missing_mask=[1, 0, 0],
    )
    stale = _record(
        original_tensor_id="tensor:stale",
        stale_mask=[0, 1, 0],
        value_shift=0.1,
    )

    result = ledger.append_snapshots([missing, stale])

    assert result.inserted_rows == 2
    assert missing["frozen_envelope"]["strict_training_ineligibility_reasons"] == [
        MISSING_FEATURE_INELIGIBILITY_REASON
    ]
    assert stale["frozen_envelope"]["strict_training_ineligibility_reasons"] == [
        STALE_FEATURE_INELIGIBILITY_REASON
    ]
    assert (
        ledger.query_fixed_cutoff(
            decision_time_cutoff=_utc(BASE + timedelta(days=1)),
            training_observed_at=_utc(datetime.now(tz=UTC) + timedelta(minutes=1)),
        )
        == []
    )
    assert ledger.verify_integrity_streaming().verified_records == 2


def test_legacy_v1_import_is_permanently_strict_training_ineligible(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    legacy = _record(
        provenance=PROVENANCE_LEGACY_V1_IMPORT,
        legacy_id="legacy:snapshot:1",
    )
    result = ledger.append_snapshot(legacy)
    fetched = ledger.get_snapshot(str(legacy["durable_snapshot_id"]))

    assert result.inserted_rows == 1
    assert fetched is not None
    assert fetched.record["frozen_envelope"]["strict_training_eligible"] is False
    assert fetched.record["frozen_envelope"]["strict_training_ineligibility_reasons"] == [
        LEGACY_INELIGIBILITY_REASON
    ]
    assert (
        ledger.query_fixed_cutoff(
            decision_time_cutoff=_utc(BASE + timedelta(days=1)),
            training_observed_at=_utc(datetime.now(tz=UTC) + timedelta(minutes=1)),
        )
        == []
    )
    legacy_without_original_receipts = _record(
        original_tensor_id="tensor:legacy:no-receipts",
        provenance=PROVENANCE_LEGACY_V1_IMPORT,
        legacy_id="legacy:snapshot:no-receipts",
        receipts=[],
        availability=[0, 0],
    )

    imported = ledger.append_snapshot(legacy_without_original_receipts)

    assert imported.inserted_rows == 1
    assert (
        ledger.query_fixed_cutoff(
            decision_time_cutoff=_utc(BASE + timedelta(days=1)),
            training_observed_at=_utc(datetime.now(tz=UTC) + timedelta(minutes=1)),
        )
        == []
    )


def test_hard_slot_append_and_query_bounds_fail_before_unbounded_work(
    tmp_path: Path,
) -> None:
    too_many_names = [f"feature_{index}" for index in range(MAX_FEATURE_SLOTS + 1)]
    with pytest.raises(FeatureSnapshotValidationError, match="FEATURE_SLOT_COUNT_INVALID"):
        _record(
            feature_names=too_many_names,
            values=[0.0] * len(too_many_names),
            missing_mask=[0] * len(too_many_names),
            stale_mask=[0] * len(too_many_names),
        )

    too_many_sources = [f"source_{index}" for index in range(MAX_SOURCE_RECEIPTS + 1)]
    receipts = [_source_receipt(label) for label in too_many_sources]
    with pytest.raises(FeatureSnapshotValidationError, match="SOURCE_RECEIPT_COUNT_EXCEEDED"):
        _record(
            source_labels=["closed_5m"],
            receipts=receipts,
            availability=[1],
        )

    ledger = _ledger(tmp_path)
    record = _record()
    with pytest.raises(FeatureSnapshotLedgerError, match="append_row_limit"):
        ledger.append_snapshots(copy.deepcopy(record) for _ in range(MAX_APPEND_ROWS + 1))
    with pytest.raises(FeatureSnapshotLedgerError, match="query_row_limit_invalid"):
        ledger.query_fixed_cutoff(
            decision_time_cutoff=_utc(BASE + timedelta(days=1)),
            training_observed_at=_utc(BASE + timedelta(days=1)),
            limit=MAX_QUERY_ROWS + 1,
        )


def test_append_and_query_byte_budgets_fail_closed_without_large_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _ledger(tmp_path)
    record = _record()
    ledger.append_snapshot(record)

    monkeypatch.setattr(ledger_module, "MAX_QUERY_BYTES", 1)
    with pytest.raises(FeatureSnapshotLedgerError, match="query_bytes_exceeded"):
        ledger.query_fixed_cutoff(
            decision_time_cutoff=_utc(BASE + timedelta(days=1)),
            training_observed_at=_utc(datetime.now(tz=UTC) + timedelta(minutes=1)),
        )
    monkeypatch.setattr(ledger_module, "MAX_APPEND_BYTES", 1)
    with pytest.raises(FeatureSnapshotLedgerError, match="append_bytes_exceeded"):
        ledger.append_snapshot(_record(original_tensor_id="tensor:byte-bound", value_shift=0.4))


def test_projection_outbox_is_atomic_immutable_and_bound_to_append_receipt(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    records = [
        _record(original_tensor_id="tensor:1"),
        _record(original_tensor_id="tensor:2", value_shift=0.1),
    ]
    result = ledger.append_snapshots(records)
    outbox = ledger.query_projection_outbox()

    assert result.inserted_rows == 2
    assert len(outbox) == 2
    assert {row.projection["append_transaction_id"] for row in outbox} == {result.transaction_id}
    assert {row.projection["durable_snapshot_id"] for row in outbox} == {
        record["durable_snapshot_id"] for record in records
    }
    assert all(row.append_receipt_sha256 == result.append_receipt_sha256 for row in outbox)
    assert all(row.postcommit_receipt_sha256 == result.postcommit_receipt_sha256 for row in outbox)
    connection = sqlite3.connect(ledger.path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            connection.execute(
                "UPDATE feature_snapshot_projection_outbox SET prepared_at = ?",
                (_utc(BASE),),
            )
    finally:
        connection.close()
    report = ledger.verify_integrity_streaming(chunk_size=1)
    assert report.integrity_verified is True
    assert report.verified_projection_outbox_rows == 2


def test_sqlite_durability_pragmas_foreign_keys_and_immutable_rows(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    ledger.append_snapshot(_record())
    connection = sqlite3.connect(ledger.path)
    try:
        assert str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
        assert int(connection.execute("PRAGMA synchronous").fetchone()[0]) == 2
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("PRAGMA foreign_key_check").fetchone() is None
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            connection.execute("UPDATE feature_snapshot_records SET symbol = 'ETHUSDT'")
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            connection.execute("DELETE FROM feature_snapshot_append_receipts")
    finally:
        connection.close()


def test_empty_preexisting_sqlite_path_initializes_atomically(tmp_path: Path) -> None:
    path = tmp_path / "preexisting.sqlite3"
    path.touch()
    ledger = DurableFeatureSnapshotLedger(path)

    result = ledger.append_snapshot(_record())

    assert result.inserted_rows == 1
    assert ledger.verify_integrity_streaming().integrity_verified is True


def test_foreign_schema_is_rejected_readonly_before_wal_side_effects(tmp_path: Path) -> None:
    path = tmp_path / "foreign.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE foreign_owner(value TEXT)")
        connection.execute("INSERT INTO foreign_owner VALUES ('untouched')")
        connection.commit()
    finally:
        connection.close()
    before_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(
        FeatureSnapshotLedgerError,
        match="partial_or_foreign_schema",
    ):
        DurableFeatureSnapshotLedger(path).append_snapshot(_record())

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before_sha256
    assert not Path(f"{path}-wal").exists()
    assert not Path(f"{path}-shm").exists()
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("SELECT value FROM foreign_owner").fetchone() == ("untouched",)
    finally:
        connection.close()


def test_live_sqlite_schema_hash_detects_ddl_tampering(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.append_snapshot(_record())
    connection = sqlite3.connect(ledger.path)
    try:
        connection.execute("DROP INDEX feature_snapshot_symbol_timeframe_index")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(
        FeatureSnapshotLedgerError,
        match="feature_snapshot_checkpoint_provenance_unattested",
    ):
        ledger.verify_integrity_streaming()
    with pytest.raises(
        FeatureSnapshotLedgerError,
        match="feature_snapshot_checkpoint_provenance_unattested",
    ):
        ledger.query_projection_outbox()


def test_fixed_cutoff_and_projection_outbox_keyset_cursors_do_not_starve(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    first = _record(
        original_tensor_id="tensor:cursor:1",
        ppo_decision_time=_utc(BASE + timedelta(seconds=4)),
    )
    second = _record(
        original_tensor_id="tensor:cursor:2",
        value_shift=0.1,
        ppo_decision_time=_utc(BASE + timedelta(seconds=5)),
    )
    ledger.append_snapshots([first, second])
    observed = _utc(datetime.now(tz=UTC) + timedelta(minutes=1))
    cutoff = _utc(BASE + timedelta(days=1))

    first_page = ledger.query_fixed_cutoff(
        decision_time_cutoff=cutoff,
        training_observed_at=observed,
        limit=1,
    )
    assert [row.sequence for row in first_page] == [1]

    # This later append has an earlier decision clock. Sequence-keyset
    # pagination must still return it after all prior ledger rows.
    third = _record(
        original_tensor_id="tensor:cursor:3",
        value_shift=0.2,
        ppo_decision_time=_utc(BASE + timedelta(seconds=2)),
    )
    ledger.append_snapshot(third)
    second_page = ledger.query_fixed_cutoff(
        decision_time_cutoff=cutoff,
        training_observed_at=observed,
        limit=1,
        after_sequence=first_page[-1].sequence,
    )
    third_page = ledger.query_fixed_cutoff(
        decision_time_cutoff=cutoff,
        training_observed_at=observed,
        limit=1,
        after_sequence=second_page[-1].sequence,
    )
    assert [row.sequence for row in second_page + third_page] == [2, 3]

    outbox_page_1 = ledger.query_projection_outbox(limit=2)
    outbox_page_2 = ledger.query_projection_outbox(
        limit=2,
        after_sequence=outbox_page_1[-1].sequence,
    )
    assert [row.sequence for row in outbox_page_1 + outbox_page_2] == [
        1,
        2,
        3,
    ]
    with pytest.raises(FeatureSnapshotLedgerError, match="after_sequence_invalid"):
        ledger.query_fixed_cutoff(
            decision_time_cutoff=cutoff,
            training_observed_at=observed,
            after_sequence=-1,
        )
    with pytest.raises(FeatureSnapshotLedgerError, match="after_sequence_invalid"):
        ledger.query_projection_outbox(after_sequence=True)


@pytest.mark.parametrize(
    ("bound_name", "bound_value", "payload", "reason"),
    [
        ("MAX_JSON_NODES", 2, [None, None], "STRICT_JSON_MAX_NODES_EXCEEDED"),
        ("MAX_JSON_STRING_BYTES", 3, "four", "STRICT_JSON_MAX_STRING_BYTES_EXCEEDED"),
        ("MAX_JSON_MAP_ENTRIES", 1, {"a": 1, "b": 2}, "STRICT_JSON_MAX_MAP_ENTRIES_EXCEEDED"),
        ("MAX_JSON_LIST_ITEMS", 1, [1, 2], "STRICT_JSON_MAX_LIST_ITEMS_EXCEEDED"),
        ("MAX_JSON_AGGREGATE_BYTES", 3, ["aa", "bb"], "STRICT_JSON_AGGREGATE_BYTES_EXCEEDED"),
    ],
)
def test_strict_json_bounds_fail_before_serializer_invocation(
    monkeypatch: pytest.MonkeyPatch,
    bound_name: str,
    bound_value: int,
    payload: object,
    reason: str,
) -> None:
    monkeypatch.setattr(ledger_module, bound_name, bound_value)

    def serializer_must_not_run(*args: object, **kwargs: object) -> str:
        raise AssertionError("serializer_called_before_prebound_failure")

    monkeypatch.setattr(ledger_module.json, "dumps", serializer_must_not_run)
    with pytest.raises(FeatureSnapshotValidationError, match=reason):
        ledger_module.canonical_json(payload)


def test_strict_json_rejects_nan_and_receipt_evidence_tamper() -> None:
    with pytest.raises(FeatureSnapshotValidationError, match="NOT_FINITE|NONFINITE"):
        _record(values=[float("nan"), 1.0, 2.0])
    receipt = _source_receipt("closed_5m")
    receipt["read_evidence"]["read_locator"] = "tampered"
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="SOURCE_READ_EVIDENCE_SHA256_MISMATCH",
    ):
        _record(
            source_labels=["closed_5m"],
            receipts=[receipt],
            availability=[1],
        )


def test_feature_abi_hash_preserves_slot_order() -> None:
    assert feature_abi_sha256(["a", "b"]) != feature_abi_sha256(["b", "a"])
    assert ledger_module.feature_requirement_classes_for_names(
        ["paper_position_present", "last_price"]
    ) == ("OPTIONAL_EVENT_DEPENDENT", "REQUIRED")
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="FEATURE_REQUIREMENT_CLASSES_POLICY_MISMATCH",
    ):
        feature_abi_sha256(
            ["last_price"],
            ordered_feature_requirement_classes=["OPTIONAL_EVENT_DEPENDENT"],
        )
