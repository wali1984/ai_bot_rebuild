from __future__ import annotations

import sqlite3
from collections.abc import Callable, ItemsView, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    durable_feature_snapshot_ledger as ledger_module,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FEATURE_REQUIREMENT_POLICY_ID,
    PROVENANCE_CANONICAL_V3,
    DurableFeatureSnapshotLedger,
    FeatureSnapshotLedgerError,
    FeatureSnapshotReadbackError,
    FeatureSnapshotValidationError,
    build_feature_snapshot_record,
    build_source_read_receipt,
)

BASE = datetime(2025, 1, 1, tzinfo=UTC)


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _source_receipt(label: str) -> dict[str, object]:
    event_time = BASE
    return build_source_read_receipt(
        source_label=label,
        payload_type="CANONICAL_JSON_SOURCE_PAYLOAD",
        payload_sha256=("a" if label == "closed_5m" else "b") * 64,
        payload_byte_count=128,
        event_time=_utc(event_time),
        available_at=_utc(event_time + timedelta(milliseconds=100)),
        consumer_observed_at=_utc(event_time + timedelta(milliseconds=200)),
        feature_cutoff=_utc(event_time + timedelta(milliseconds=300)),
        read_locator_type="SQLITE_IMMUTABLE_ROW",
        read_locator=f"fixture.sqlite3/source/{label}",
        read_locator_version=f"row:{label}:1",
        finality_type=("CLOSED_INTERVAL" if label == "closed_5m" else "VERSIONED_SNAPSHOT"),
        finality_cutoff=_utc(event_time + timedelta(milliseconds=50)),
        finality_verified_at=_utc(event_time + timedelta(milliseconds=150)),
        finality_verifier="query-adversarial-test",
    )


def _record(*, tensor_id: str, value_shift: float) -> dict[str, object]:
    labels = ["closed_5m", "orderbook"]
    names = ["return_5m", "spread_bps", "volume_z"]
    receipts = [_source_receipt(label) for label in labels]
    receipts_by_label = {
        str(receipt["source_label"]): receipt for receipt in receipts
    }
    feature_sources = [labels[index % len(labels)] for index in range(len(names))]
    return build_feature_snapshot_record(
        provenance_classification=PROVENANCE_CANONICAL_V3,
        legacy_v1_snapshot_id=None,
        symbol="BTCUSDT",
        timeframe="5m",
        feature_snapshot_id=f"feature_snapshot:{tensor_id}",
        tensor_decision_time=_utc(BASE + timedelta(seconds=2)),
        temporal_rejection_reasons=[],
        ordered_feature_names=names,
        feature_values=[0.01 + value_shift, 2.0, -0.25],
        missing_mask=[0, 0, 0],
        stale_mask=[0, 0, 0],
        source_availability_mask=[1, 1, 1],
        ordered_feature_source_labels=feature_sources,
        feature_source_receipt_sha256s=[
            str(receipts_by_label[label]["receipt_sha256"])
            for label in feature_sources
        ],
        source_read_receipts=receipts,
        feature_requirement_policy_id=FEATURE_REQUIREMENT_POLICY_ID,
        ordered_feature_requirement_classes=["REQUIRED"] * len(names),
        original_tensor_id=tensor_id,
        source_lineage_material={
            "lineage_schema": "query_adversarial_fixture_v1",
            "ordered_sources": labels,
            "tensor_builder": "query-adversarial-test",
        },
        feature_cutoff=_utc(BASE + timedelta(seconds=1)),
        masa_feature_cutoff=_utc(BASE + timedelta(seconds=1, milliseconds=100)),
        ppo_feature_cutoff=_utc(BASE + timedelta(seconds=1, milliseconds=200)),
        ppo_decision_time=_utc(BASE + timedelta(seconds=2)),
        generated_at=_utc(BASE + timedelta(seconds=1, milliseconds=500)),
    )


def _ledger_with_three_record_transaction(tmp_path: Path) -> DurableFeatureSnapshotLedger:
    ledger = DurableFeatureSnapshotLedger(tmp_path / "query-adversarial.sqlite3")
    ledger.append_snapshots(
        [
            _record(tensor_id="tensor:query:1", value_shift=0.0),
            _record(tensor_id="tensor:query:2", value_shift=0.1),
            _record(tensor_id="tensor:query:3", value_shift=0.2),
        ]
    )
    return ledger


def _run_query(ledger: DurableFeatureSnapshotLedger, query_kind: str) -> list[Any]:
    if query_kind == "fixed_cutoff":
        return ledger.query_fixed_cutoff(
            decision_time_cutoff=_utc(BASE + timedelta(days=1)),
            training_observed_at=_utc(datetime(2100, 1, 1, tzinfo=UTC)),
        )
    if query_kind == "projection_outbox":
        return ledger.query_projection_outbox()
    raise AssertionError(f"unknown query kind: {query_kind}")


class _EncodeForbidden(str):
    def encode(self, *_: object, **__: object) -> bytes:
        raise AssertionError("UTF-8 allocation occurred before the cheap byte bound")


class _LinearMembershipForbidden(list[dict[str, Any]]):
    def __contains__(self, _: object) -> bool:
        raise AssertionError("receipt identity membership used a linear list scan")


class _HookBombDict(dict[str, object]):
    length_called = False
    iterated = False
    items_called = False

    def __len__(self) -> int:
        type(self).length_called = True
        raise AssertionError("custom mapping length hook invoked")

    def __iter__(self) -> Iterator[str]:
        type(self).iterated = True
        raise AssertionError("custom mapping iteration hook invoked")

    def items(self) -> ItemsView[str, object]:
        type(self).items_called = True
        raise AssertionError("custom mapping items hook invoked")


def test_canonical_json_rejects_multibyte_string_before_encode_or_serializer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _EncodeForbidden("éé")
    monkeypatch.setattr(ledger_module, "MAX_JSON_STRING_BYTES", 3)

    def serializer_must_not_run(*_: object, **__: object) -> str:
        raise AssertionError("JSON serializer ran before the string byte bound")

    monkeypatch.setattr(ledger_module.json, "dumps", serializer_must_not_run)
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="STRICT_JSON_MAX_STRING_BYTES_EXCEEDED",
    ):
        ledger_module.canonical_json(value)


def test_db_json_text_rejects_multibyte_payload_before_encode_or_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _EncodeForbidden('{"é":0}')

    def parser_must_not_run(*_: object, **__: object) -> object:
        raise AssertionError("JSON parser ran before the database text byte bound")

    monkeypatch.setattr(ledger_module.json, "loads", parser_must_not_run)
    with pytest.raises(FeatureSnapshotReadbackError, match="bytes_exceeded"):
        ledger_module._parse_canonical_json_object(
            value,
            reason="adversarial_db_json",
            max_bytes=len(value),
        )


def test_canonical_json_accounts_for_every_nested_token_before_serializer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"é": [1, True, None, -0.0, {"line": "\n"}]}
    encoded = ledger_module.canonical_json(payload)
    assert encoded == '{"\\u00e9":[1,true,null,-0.0,{"line":"\\n"}]}'

    monkeypatch.setattr(ledger_module, "MAX_JSON_AGGREGATE_BYTES", len(encoded) - 1)

    def serializer_must_not_run(*_: object, **__: object) -> str:
        raise AssertionError("serializer ran before exhaustive JSON byte accounting")

    monkeypatch.setattr(ledger_module.json, "dumps", serializer_must_not_run)
    with pytest.raises(
        FeatureSnapshotValidationError,
        match="STRICT_JSON_AGGREGATE_BYTES_EXCEEDED",
    ):
        ledger_module.canonical_json(payload)


def test_canonical_json_rejects_custom_mapping_without_invoking_hooks() -> None:
    value = _HookBombDict({"safe": 1})
    type(value).length_called = False
    type(value).iterated = False
    type(value).items_called = False

    with pytest.raises(FeatureSnapshotValidationError, match="STRICT_JSON_UNSUPPORTED_TYPE"):
        ledger_module.canonical_json(value)

    assert type(value).length_called is False
    assert type(value).iterated is False
    assert type(value).items_called is False


def test_db_json_rejects_invalid_utf8_scalar_before_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def parser_must_not_run(*_: object, **__: object) -> object:
        raise AssertionError("parser ran before UTF-8 scalar validation")

    monkeypatch.setattr(ledger_module.json, "loads", parser_must_not_run)
    with pytest.raises(FeatureSnapshotReadbackError, match="invalid_utf8"):
        ledger_module._parse_canonical_json_object(
            '{"bad":"\ud800"}',
            reason="adversarial_db_json",
        )


@pytest.mark.parametrize("query_kind", ["fixed_cutoff", "projection_outbox"])
def test_query_validates_transaction_proof_once_and_each_projection_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    query_kind: str,
) -> None:
    ledger = _ledger_with_three_record_transaction(tmp_path)
    counts = {
        "_validated_record_row": 0,
        "_validated_append_receipt_row": 0,
        "_validated_postcommit_row": 0,
        "_validated_head_row": 0,
        "_validated_projection_row": 0,
    }

    for method_name in counts:
        original = getattr(DurableFeatureSnapshotLedger, method_name)

        def counted(
            row: sqlite3.Row,
            *,
            _method_name: str = method_name,
            _original: Callable[[sqlite3.Row], dict[str, Any]] = original,
        ) -> dict[str, Any]:
            counts[_method_name] += 1
            return _original(row)

        monkeypatch.setattr(
            DurableFeatureSnapshotLedger,
            method_name,
            staticmethod(counted),
        )

    assert len(_run_query(ledger, query_kind)) == 3
    assert counts == {
        "_validated_record_row": 3,
        "_validated_append_receipt_row": 1,
        "_validated_postcommit_row": 1,
        "_validated_head_row": 1,
        "_validated_projection_row": 3,
    }


@pytest.mark.parametrize("query_kind", ["fixed_cutoff", "projection_outbox"])
def test_query_uses_constant_time_receipt_identity_membership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    query_kind: str,
) -> None:
    ledger = _ledger_with_three_record_transaction(tmp_path)
    original = DurableFeatureSnapshotLedger._validated_append_receipt_row

    def forbid_linear_membership(row: sqlite3.Row) -> dict[str, Any]:
        receipt = original(row)
        receipt["inserted_identities"] = _LinearMembershipForbidden(
            receipt["inserted_identities"]
        )
        return receipt

    monkeypatch.setattr(
        DurableFeatureSnapshotLedger,
        "_validated_append_receipt_row",
        staticmethod(forbid_linear_membership),
    )

    assert len(_run_query(ledger, query_kind)) == 3


@pytest.mark.parametrize("query_kind", ["fixed_cutoff", "projection_outbox"])
def test_query_enforces_total_sql_material_row_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    query_kind: str,
) -> None:
    ledger = _ledger_with_three_record_transaction(tmp_path)
    monkeypatch.setattr(ledger_module, "MAX_QUERY_SQL_ROWS", 1)

    with pytest.raises(FeatureSnapshotLedgerError, match="query_sql_rows_exceeded"):
        _run_query(ledger, query_kind)


@pytest.mark.parametrize("query_kind", ["fixed_cutoff", "projection_outbox"])
def test_query_runs_inside_strict_readonly_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    query_kind: str,
) -> None:
    ledger = _ledger_with_three_record_transaction(tmp_path)
    original = DurableFeatureSnapshotLedger._attest_query_snapshot
    observed = {"called": False}

    def assert_snapshot(
        self: DurableFeatureSnapshotLedger,
        connection: sqlite3.Connection,
        **kwargs: Any,
    ) -> None:
        observed["called"] = True
        assert connection.in_transaction is True
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        assert connection.execute("PRAGMA read_uncommitted").fetchone()[0] == 0
        original(self, connection, **kwargs)

    monkeypatch.setattr(
        DurableFeatureSnapshotLedger,
        "_attest_query_snapshot",
        assert_snapshot,
    )

    assert len(_run_query(ledger, query_kind)) == 3
    assert observed["called"] is True


def _json_blob_lengths(ledger: DurableFeatureSnapshotLedger) -> dict[str, int]:
    connection = sqlite3.connect(ledger.path)
    try:
        return {
            "record": int(
                connection.execute(
                    "SELECT length(CAST(record_json AS BLOB)) FROM feature_snapshot_records LIMIT 1"
                ).fetchone()[0]
            ),
            "projection": int(
                connection.execute(
                    "SELECT length(CAST(projection_json AS BLOB)) "
                    "FROM feature_snapshot_projection_outbox LIMIT 1"
                ).fetchone()[0]
            ),
        }
    finally:
        connection.close()


@pytest.mark.parametrize("query_kind", ["fixed_cutoff", "projection_outbox"])
def test_query_byte_budget_includes_transaction_receipt_postcommit_and_head_proofs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    query_kind: str,
) -> None:
    ledger = _ledger_with_three_record_transaction(tmp_path)
    lengths = _json_blob_lengths(ledger)
    if query_kind == "fixed_cutoff":
        # This covers exactly the bytes the old path counted: returned record
        # JSON plus the transaction's projection proof JSON.
        old_path_budget = 3 * lengths["record"] + 3 * lengths["projection"]
    else:
        # The old outbox path counted every projection twice and no record or
        # receipt/postcommit/head JSON.
        old_path_budget = 6 * lengths["projection"]
    monkeypatch.setattr(ledger_module, "MAX_QUERY_BYTES", old_path_budget)

    with pytest.raises(FeatureSnapshotLedgerError, match="query_bytes_exceeded"):
        _run_query(ledger, query_kind)


@pytest.mark.parametrize("query_kind", ["fixed_cutoff", "projection_outbox"])
def test_oversized_record_is_blocked_before_record_json_parser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    query_kind: str,
) -> None:
    ledger = _ledger_with_three_record_transaction(tmp_path)
    record_bytes = _json_blob_lengths(ledger)["record"]
    monkeypatch.setattr(ledger_module, "MAX_RECORD_BYTES", record_bytes - 1)
    original = ledger_module._parse_canonical_json_object

    def parser_guard(
        value: object,
        *,
        reason: str,
        max_bytes: int = ledger_module.MAX_APPEND_BYTES,
    ) -> dict[str, Any]:
        if reason == "feature_snapshot_record_json_invalid":
            raise AssertionError("oversized record crossed the SQL/readback byte guard")
        return original(value, reason=reason, max_bytes=max_bytes)

    monkeypatch.setattr(ledger_module, "_parse_canonical_json_object", parser_guard)
    with pytest.raises(FeatureSnapshotLedgerError, match="bytes_exceeded"):
        _run_query(ledger, query_kind)


def _tamper_head_json_while_preserving_schema(ledger: DurableFeatureSnapshotLedger) -> None:
    connection = sqlite3.connect(ledger.path)
    connection.row_factory = sqlite3.Row
    try:
        schema_before = ledger_module._sqlite_schema_sha256(connection)
        trigger_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
            ("feature_snapshot_ledger_heads_no_update",),
        ).fetchone()
        assert trigger_row is not None
        trigger_sql = str(trigger_row["sql"])
        connection.execute("DROP TRIGGER feature_snapshot_ledger_heads_no_update")
        connection.execute("UPDATE feature_snapshot_ledger_heads SET head_json = '{}' ")
        connection.execute(trigger_sql)
        connection.commit()
        assert ledger_module._sqlite_schema_sha256(connection) == schema_before
    finally:
        connection.close()


def _tamper_tail_chain_while_preserving_schema(
    ledger: DurableFeatureSnapshotLedger,
) -> None:
    connection = sqlite3.connect(ledger.path)
    connection.row_factory = sqlite3.Row
    try:
        schema_before = ledger_module._sqlite_schema_sha256(connection)
        trigger_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
            ("feature_snapshot_records_no_update",),
        ).fetchone()
        assert trigger_row is not None
        trigger_sql = str(trigger_row["sql"])
        connection.execute("DROP TRIGGER feature_snapshot_records_no_update")
        connection.execute(
            """
            UPDATE feature_snapshot_records
            SET record_chain_sha256 = ?
            WHERE sequence = (SELECT MAX(sequence) FROM feature_snapshot_records)
            """,
            ("c" * 64,),
        )
        connection.execute(trigger_sql)
        connection.commit()
        assert ledger_module._sqlite_schema_sha256(connection) == schema_before
    finally:
        connection.close()


@pytest.mark.parametrize("query_kind", ["fixed_cutoff", "projection_outbox"])
def test_query_validates_full_ledger_head_not_only_head_sequence(
    tmp_path: Path,
    query_kind: str,
) -> None:
    ledger = _ledger_with_three_record_transaction(tmp_path)
    _tamper_head_json_while_preserving_schema(ledger)

    with pytest.raises(FeatureSnapshotReadbackError, match="ledger_head_invalid"):
        _run_query(ledger, query_kind)


@pytest.mark.parametrize("query_kind", ["fixed_cutoff", "projection_outbox"])
def test_query_validates_tail_chain_before_returning_any_row(
    tmp_path: Path,
    query_kind: str,
) -> None:
    ledger = _ledger_with_three_record_transaction(tmp_path)
    _tamper_tail_chain_while_preserving_schema(ledger)

    with pytest.raises(FeatureSnapshotReadbackError, match="record_chain_mismatch"):
        _run_query(ledger, query_kind)
