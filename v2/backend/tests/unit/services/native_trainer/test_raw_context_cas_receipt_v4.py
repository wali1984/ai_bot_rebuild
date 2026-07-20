from __future__ import annotations

import hashlib
import json
import sys
import threading
from pathlib import Path
from typing import Any, NoReturn, cast

import pytest

from tools import trainer_raw_context_cas_receipt_v4 as receipt_module
from tools.trainer_raw_context_cas_receipt_v4 import (
    RAW_CONTEXT_AUTHENTICATION_LIMITATIONS,
    RAW_CONTEXT_CAS_RECEIPT_V4_SCHEMA_VERSION,
    RawContextCasReceiptArtifactV4,
    RawContextCasReceiptV4ValidationError,
    build_raw_context_cas_receipt_v4,
    canonical_raw_context_bytes_v4,
)
from v2.backend.app.services.native_trainer.feature_snapshot_publication_ledger_v4 import (
    FeatureSnapshotPublicationLedgerEntryV4,
    FeatureSnapshotPublicationLedgerV4,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_feature_snapshot_publication_ledger_v4 as publication_harness,
)

_CODE_SHA256 = "a" * 64
_CONFIG_SHA256 = "b" * 64


def _canonical_payload_bytes(value: object) -> bytes:
    return receipt_module._canonical_json(
        value,
        max_bytes=receipt_module.MAX_RAW_CONTEXT_V4_BYTES,
    ).encode("ascii")


def _raw_context_bytes(
    publication: dict[str, Any],
    *,
    payload: object | None = None,
) -> bytes:
    artifact = cast(dict[str, Any], publication["feature_artifact_binding"])
    latest = cast(
        dict[str, Any],
        publication["source_provenance_binding"]["latest_candle"],
    )
    return canonical_raw_context_bytes_v4(
        feature_snapshot_id=artifact["feature_snapshot_id"],
        symbol=artifact["symbol"],
        timeframe=artifact["timeframe"],
        candle_open_time=artifact["candle_open_time"],
        candle_close_time=artifact["candle_close_time"],
        economic_event_time=latest["economic_event_time"],
        raw_context_observed_at=artifact["source_ingested_at"],
        raw_context_available_at=artifact["source_available_at"],
        raw_context_capture_completed_at=artifact["generated_at"],
        producer_id="tensor-builder-context-capture",
        producer_version="v4",
        producer_code_sha256=_CODE_SHA256,
        producer_config_sha256=_CONFIG_SHA256,
        payload_json_bytes=_canonical_payload_bytes(
            {
                "market": {"close": 102.0, "volume": 14.0},
                "optional_event_sources": {},
            }
            if payload is None
            else payload
        ),
    )


def _standalone_raw_context_from_payload_bytes(payload_json_bytes: object) -> bytes:
    return canonical_raw_context_bytes_v4(
        feature_snapshot_id="v2_fsnap_" + "1" * 64,
        symbol="BTCUSDT",
        timeframe="1m",
        candle_open_time="2026-07-20T00:00:00.000000Z",
        candle_close_time="2026-07-20T00:01:00.000000Z",
        economic_event_time="2026-07-20T00:01:00.000000Z",
        raw_context_observed_at="2026-07-20T00:01:00.000001Z",
        raw_context_available_at="2026-07-20T00:01:00.000002Z",
        raw_context_capture_completed_at="2026-07-20T00:01:00.000003Z",
        producer_id="tensor-builder-context-capture",
        producer_version="v4",
        producer_code_sha256=_CODE_SHA256,
        producer_config_sha256=_CONFIG_SHA256,
        payload_json_bytes=payload_json_bytes,
    )


def _standalone_raw_context_bytes(payload: object) -> bytes:
    return _standalone_raw_context_from_payload_bytes(_canonical_payload_bytes(payload))


def _harness(
    tmp_path: Path,
) -> tuple[
    FeatureSnapshotPublicationLedgerV4,
    FeatureSnapshotPublicationLedgerEntryV4,
    ImmutableSourcePayloadStore,
    bytes,
    RawContextCasReceiptArtifactV4,
]:
    root = tmp_path / "raw-context-receipt-harness"
    ledger, source_result, feature_artifact, recorded_at = publication_harness._harness(root)
    publication_result = publication_harness._append(
        ledger,
        source_result,
        feature_artifact,
        recorded_at,
    )
    raw_context = _raw_context_bytes(publication_result.entry.record)
    store = ImmutableSourcePayloadStore(root / "raw-context-cas")
    receipt = build_raw_context_cas_receipt_v4(
        raw_context_bytes=raw_context,
        source_payload_store=store,
        publication_ledger=ledger,
        publication_entry=publication_result.entry,
    )
    return ledger, publication_result.entry, store, raw_context, receipt


def _coherently_encode_document(document: dict[str, Any]) -> bytes:
    material = {key: item for key, item in document.items() if key != "document_binding_sha256"}
    document["document_binding_sha256"] = receipt_module._sha256_json(
        material,
        max_bytes=receipt_module.MAX_RAW_CONTEXT_V4_BYTES,
    )
    return receipt_module._canonical_json(
        document,
        max_bytes=receipt_module.MAX_RAW_CONTEXT_V4_BYTES,
    ).encode("ascii")


@pytest.mark.parametrize(
    "value",
    [
        "",
        'quote"slash\\',
        "\b\t\n\f\r",
        "\x00\x1f\x7f",
        "\u0080\uffff\U0001f600\ud800",
        0.0,
        -0.0,
        5e-324,
        1.7976931348623157e308,
        1e20,
        1e-7,
    ],
)
def test_preflight_exactly_matches_canonical_escape_and_float_widths(
    value: object,
) -> None:
    expected = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert receipt_module._preflight_canonical_json(value, max_bytes=1024) == len(
        expected.encode("ascii")
    )
    assert receipt_module._canonical_json(value, max_bytes=1024) == expected


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("oversized_bytes", "PAYLOAD_BYTES_SIZE_INVALID"),
        ("node_limit", "JSON_NODE_LIMIT_EXCEEDED"),
    ],
)
def test_huge_immutable_payload_is_rejected_before_snapshot_or_serialization(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    reason: str,
) -> None:
    if case == "oversized_bytes":
        payload_json_bytes = b'{"huge":"' + b"x" * receipt_module.MAX_RAW_CONTEXT_V4_BYTES + b'"}'
    else:
        payload_json_bytes = (
            b'{"huge":[' + b"null," * receipt_module.MAX_RAW_CONTEXT_JSON_NODES + b"null]}"
        )

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("preflight must reject before snapshot or json.dumps")

    monkeypatch.setattr(receipt_module, "_strict_json_snapshot", forbidden)
    monkeypatch.setattr(json, "dumps", forbidden)

    with pytest.raises(RawContextCasReceiptV4ValidationError, match=reason):
        _standalone_raw_context_from_payload_bytes(payload_json_bytes)


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ({"k" * 128: 0}, "JSON_KEY_SIZE_LIMIT_EXCEEDED"),
        ({"value": "x" * 128}, "JSON_STRING_SIZE_LIMIT_EXCEEDED"),
        ([None] * 64, "JSON_CONTAINER_SIZE_LIMIT_EXCEEDED"),
        (1 << 4096, "JSON_INTEGER_SIZE_LIMIT_EXCEEDED"),
    ],
)
def test_scalar_and_container_limits_reject_before_json_dumps(
    monkeypatch: pytest.MonkeyPatch,
    value: object,
    reason: str,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("bounded preflight must run before json.dumps")

    monkeypatch.setattr(json, "dumps", forbidden)
    with pytest.raises(RawContextCasReceiptV4ValidationError, match=reason):
        receipt_module._canonical_json(value, max_bytes=64)


def test_python_huge_integer_conversion_limit_fails_before_json_dumps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("integer preflight must run before json.dumps")

    original_limit = sys.get_int_max_str_digits()
    try:
        sys.set_int_max_str_digits(4300)
        monkeypatch.setattr(json, "dumps", forbidden)
        with pytest.raises(
            RawContextCasReceiptV4ValidationError,
            match="JSON_INTEGER_SIZE_LIMIT_EXCEEDED",
        ):
            receipt_module._canonical_json(
                1 << 100_000,
                max_bytes=receipt_module.MAX_RAW_CONTEXT_V4_BYTES,
            )
    finally:
        sys.set_int_max_str_digits(original_limit)


def test_exact_maximum_document_is_deterministic_and_one_byte_more_rejects() -> None:
    empty = _standalone_raw_context_bytes({"blob": ""})
    fill_count = receipt_module.MAX_RAW_CONTEXT_V4_BYTES - len(empty)
    payload = {"blob": "z" * fill_count}

    first = _standalone_raw_context_bytes(payload)
    second = _standalone_raw_context_bytes(payload)

    assert len(first) == receipt_module.MAX_RAW_CONTEXT_V4_BYTES
    assert first == second
    assert json.loads(first)["payload"] == payload

    with pytest.raises(
        RawContextCasReceiptV4ValidationError,
        match="JSON_STRING_SIZE_LIMIT_EXCEEDED",
    ):
        _standalone_raw_context_bytes({"blob": "z" * (fill_count + 1)})


def test_receipt_pins_exact_bytes_and_only_claims_narrow_audit_facts(
    tmp_path: Path,
) -> None:
    ledger, entry, store, raw_context, artifact = _harness(tmp_path)
    receipt = artifact.receipt
    raw_document = json.loads(raw_context)

    assert artifact.schema_version == RAW_CONTEXT_CAS_RECEIPT_V4_SCHEMA_VERSION
    assert artifact.raw_context_sha256 == hashlib.sha256(raw_context).hexdigest()
    assert artifact.raw_context_byte_count == len(raw_context)
    assert artifact.raw_context_bytes == raw_context
    assert receipt["raw_context_sha256"] == artifact.raw_context_sha256
    assert receipt["authentication_limitations"] == list(RAW_CONTEXT_AUTHENTICATION_LIMITATIONS)
    assert receipt["context_locator"] == raw_document["context_locator"]
    assert receipt["snapshot_identity"] == raw_document["snapshot_identity"]
    assert receipt["temporal_identity"] == raw_document["temporal_identity"]
    assert receipt["producer_identity"] == raw_document["producer_identity"]
    assert "event_time" not in receipt["temporal_identity"]

    cas = receipt["raw_context_cas_binding"]
    assert cas["payload_sha256"] == artifact.raw_context_sha256
    assert cas["payload_byte_count"] == len(raw_context)
    assert store.get(cas["payload_sha256"], expected_byte_count=len(raw_context)) == raw_context

    association = receipt["p0d_ledger_association"]
    assert association["ledger_sequence"] == entry.ledger_sequence
    assert association["ledger_entry_sha256"] == entry.entry_sha256
    assert association["feature_snapshot_id"] == entry.feature_snapshot_id
    assert association["committed_head_and_owned_cas_fresh_read_verified"] is True
    assert ledger.read_entries()[0].entry_sha256 == entry.entry_sha256

    for name in receipt_module._TRUE_FIELDS:
        assert receipt[name] is True
        assert getattr(artifact, name) is True
    for name in receipt_module._FALSE_FIELDS:
        assert receipt[name] is False
        assert getattr(artifact, name) is False


def test_immutable_payload_boundary_has_no_caller_owned_mutable_aliases(
    tmp_path: Path,
) -> None:
    ledger, entry, store, _raw_context, _artifact = _harness(tmp_path)
    mutable_payload: dict[str, Any] = {"market": {"close": 102.0}, "events": []}
    payload_json_bytes = _canonical_payload_bytes(mutable_payload)
    raw_context = _standalone_raw_context_from_payload_bytes(payload_json_bytes)
    mutable_payload["market"]["close"] = 999.0
    mutable_payload["events"].append("future-event")
    payload_json_bytes = _canonical_payload_bytes(mutable_payload)

    captured = json.loads(raw_context)["payload"]
    assert captured == {"events": [], "market": {"close": 102.0}}
    assert json.loads(payload_json_bytes) == mutable_payload

    for mutable_or_aliased in (
        mutable_payload,
        bytearray(b"{}"),
        memoryview(b"{}"),
        "{}",
    ):
        with pytest.raises(
            RawContextCasReceiptV4ValidationError,
            match="IMMUTABLE_PAYLOAD_BYTES_REQUIRED",
        ):
            _standalone_raw_context_from_payload_bytes(mutable_or_aliased)

    with pytest.raises(
        RawContextCasReceiptV4ValidationError,
        match="EXACT_BYTES_REQUIRED",
    ):
        build_raw_context_cas_receipt_v4(
            raw_context_bytes=cast(Any, bytearray(raw_context)),
            source_payload_store=store,
            publication_ledger=ledger,
            publication_entry=entry,
        )

    noncanonical = json.dumps(json.loads(raw_context), indent=2).encode("ascii")
    with pytest.raises(
        RawContextCasReceiptV4ValidationError,
        match="NOT_EXACT_CANONICAL_JSON",
    ):
        build_raw_context_cas_receipt_v4(
            raw_context_bytes=noncanonical,
            source_payload_store=store,
            publication_ledger=ledger,
            publication_entry=entry,
        )


@pytest.mark.parametrize(
    ("payload_json_bytes", "reason"),
    [
        (b'{"a": 1}', "PAYLOAD_BYTES_NOT_EXACT_CANONICAL_JSON"),
        (b'{"z":0,"a":1}', "PAYLOAD_BYTES_NOT_EXACT_CANONICAL_JSON"),
        (b'{"a":1,"a":2}', "DUPLICATE_JSON_KEY"),
        (b'{"value":NaN}', "JSON_CONSTANT_FORBIDDEN"),
        (b'{"value":Infinity}', "JSON_CONSTANT_FORBIDDEN"),
        ('{"value":"\u00e9"}'.encode(), "PAYLOAD_JSON_INVALID"),
        (b"[]", "PAYLOAD_NOT_EXACT_OBJECT"),
        (b"null", "PAYLOAD_NOT_EXACT_OBJECT"),
    ],
)
def test_payload_bytes_must_be_exact_canonical_strict_json_object(
    payload_json_bytes: bytes,
    reason: str,
) -> None:
    with pytest.raises(RawContextCasReceiptV4ValidationError, match=reason):
        _standalone_raw_context_from_payload_bytes(payload_json_bytes)


def test_replacing_callers_bytes_reference_cannot_change_inflight_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_parser = receipt_module._parse_exact_canonical_payload_bytes
    parser_entered = threading.Event()
    continue_parse = threading.Event()
    caller_reference = [_canonical_payload_bytes({"state": "before"})]
    result: list[bytes] = []
    errors: list[BaseException] = []

    def coordinated_parser(value: object) -> dict[str, Any]:
        parser_entered.set()
        if not continue_parse.wait(timeout=5):
            raise AssertionError("test did not release immutable payload parser")
        return original_parser(value)

    def capture() -> None:
        try:
            result.append(_standalone_raw_context_from_payload_bytes(caller_reference[0]))
        except BaseException as exc:  # pragma: no cover - assertion aid
            errors.append(exc)

    monkeypatch.setattr(
        receipt_module,
        "_parse_exact_canonical_payload_bytes",
        coordinated_parser,
    )
    worker = threading.Thread(target=capture)
    worker.start()
    assert parser_entered.wait(timeout=5)
    caller_reference[0] = _canonical_payload_bytes({"state": "after"})
    continue_parse.set()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert errors == []
    assert json.loads(result[0])["payload"] == {"state": "before"}


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda row: row["temporal_identity"].__setitem__(
                "raw_context_available_at",
                "2023-11-14T23:23:59.999000Z",
            ),
            "CAPTURE_CLOCK_ORDER_INVALID",
        ),
        (
            lambda row: row["temporal_identity"].__setitem__("candle_final", False),
            "CANDLE_NOT_FINAL",
        ),
        (
            lambda row: row["temporal_identity"].__setitem__(
                "economic_event_time",
                row["temporal_identity"]["candle_open_time"],
            ),
            "ECONOMIC_EVENT_NOT_CANDLE_CLOSE",
        ),
    ],
)
def test_clock_inversion_nonfinal_and_economic_clock_substitution_fail_closed(
    tmp_path: Path,
    mutation: Any,
    reason: str,
) -> None:
    ledger, entry, store, raw_context, _artifact = _harness(tmp_path)
    document = json.loads(raw_context)
    mutation(document)
    candidate = _coherently_encode_document(document)

    with pytest.raises(RawContextCasReceiptV4ValidationError, match=reason):
        build_raw_context_cas_receipt_v4(
            raw_context_bytes=candidate,
            source_payload_store=store,
            publication_ledger=ledger,
            publication_entry=entry,
        )


def test_namespace_locator_and_snapshot_substitution_fail_closed(tmp_path: Path) -> None:
    ledger, entry, store, raw_context, _artifact = _harness(tmp_path)

    wrong_namespace = json.loads(raw_context)
    wrong_namespace["context_locator"]["namespace"] = "trainer-other-context-v4"
    locator_material = {
        key: item
        for key, item in wrong_namespace["context_locator"].items()
        if key != "locator_sha256"
    }
    wrong_namespace["context_locator"]["locator_sha256"] = receipt_module._sha256_json(
        locator_material
    )
    with pytest.raises(
        RawContextCasReceiptV4ValidationError,
        match="NAMESPACE_OR_LOCATOR_MISMATCH",
    ):
        build_raw_context_cas_receipt_v4(
            raw_context_bytes=_coherently_encode_document(wrong_namespace),
            source_payload_store=store,
            publication_ledger=ledger,
            publication_entry=entry,
        )

    wrong_snapshot = json.loads(raw_context)
    wrong_snapshot["snapshot_identity"]["feature_snapshot_id"] = "snapshot-other-v4"
    wrong_snapshot["context_locator"] = receipt_module._locator(wrong_snapshot["snapshot_identity"])
    with pytest.raises(
        RawContextCasReceiptV4ValidationError,
        match="SNAPSHOT_IDENTITY_MISMATCH",
    ):
        build_raw_context_cas_receipt_v4(
            raw_context_bytes=_coherently_encode_document(wrong_snapshot),
            source_payload_store=store,
            publication_ledger=ledger,
            publication_entry=entry,
        )


@pytest.mark.parametrize(
    "promoted_field",
    [
        "trainer_admission_granted",
        "upstream_payload_construction_independently_attested",
    ],
)
def test_coherently_rehashed_receipt_cannot_promote_any_authorization_or_attestation(
    tmp_path: Path,
    promoted_field: str,
) -> None:
    ledger, entry, store, raw_context, artifact = _harness(tmp_path)
    forged = json.loads(artifact.receipt_json)
    forged[promoted_field] = True
    material = {key: item for key, item in forged.items() if key != "receipt_sha256"}
    forged["receipt_sha256"] = receipt_module._sha256_json(material)

    with pytest.raises(
        RawContextCasReceiptV4ValidationError,
        match="CONSTANT_OR_FLAG_MISMATCH",
    ):
        RawContextCasReceiptArtifactV4(
            schema_version=artifact.schema_version,
            raw_context_sha256=artifact.raw_context_sha256,
            raw_context_byte_count=artifact.raw_context_byte_count,
            receipt_sha256=forged["receipt_sha256"],
            receipt_json=receipt_module._canonical_json(
                forged,
                max_bytes=receipt_module.MAX_RAW_CONTEXT_RECEIPT_V4_BYTES,
            ),
            _raw_context_bytes=raw_context,
            _source_payload_store=store,
            _publication_ledger=ledger,
            _publication_entry=entry,
            _construction_token=receipt_module._CONSTRUCTION_TOKEN,
        )


def test_raw_context_cas_truncation_is_detected_on_every_access(tmp_path: Path) -> None:
    _ledger, _entry, store, raw_context, artifact = _harness(tmp_path)
    object_path = store.path_for(artifact.raw_context_sha256)
    object_path.chmod(0o600)
    object_path.write_bytes(raw_context[: len(raw_context) // 2])
    object_path.chmod(0o400)

    with pytest.raises(
        RawContextCasReceiptV4ValidationError,
        match="CAS_REVALIDATION_FAILED",
    ):
        _ = artifact.receipt


def test_raw_context_cas_symlink_and_root_path_swaps_fail_closed(tmp_path: Path) -> None:
    _ledger, _entry, store, _raw_context, artifact = _harness(tmp_path)
    object_path = store.path_for(artifact.raw_context_sha256)
    moved_object = object_path.with_name(f"{object_path.name}.moved")
    object_path.rename(moved_object)
    object_path.symlink_to(moved_object.name)
    with pytest.raises(
        RawContextCasReceiptV4ValidationError,
        match="CAS_REVALIDATION_FAILED",
    ):
        _ = artifact.receipt

    object_path.unlink()
    moved_object.rename(object_path)
    root = store.root_path
    moved_root = root.with_name(f"{root.name}.moved")
    root.rename(moved_root)
    root.symlink_to(moved_root.name, target_is_directory=True)
    with pytest.raises(
        RawContextCasReceiptV4ValidationError,
        match="CAS_REVALIDATION_FAILED",
    ):
        _ = artifact.receipt


def test_p0d_ledger_truncation_is_detected_on_every_access(tmp_path: Path) -> None:
    ledger, _entry, _store, _raw_context, artifact = _harness(tmp_path)
    ledger.path.write_bytes(b"")
    ledger.path.chmod(0o600)

    with pytest.raises(
        RawContextCasReceiptV4ValidationError,
        match="P0D_REVALIDATION_FAILED",
    ):
        _ = artifact.receipt


def test_runtime_remains_unwired_and_module_has_no_io_clients() -> None:
    repo = Path(__file__).resolve().parents[6]
    app_root = repo / "v2" / "backend" / "app"
    runtime_imports = [
        path
        for path in app_root.rglob("*.py")
        if "trainer_raw_context_cas_receipt_v4"
        in path.read_text(
            encoding="utf-8",
            errors="ignore",
        )
    ]
    assert runtime_imports == []

    module_source = (repo / "tools" / "trainer_raw_context_cas_receipt_v4.py").read_text(
        encoding="utf-8"
    )
    assert '"event_time"' not in module_source
    for forbidden_import in (
        "import redis",
        "import requests",
        "import httpx",
        "import socket",
        "import subprocess",
    ):
        assert forbidden_import not in module_source
