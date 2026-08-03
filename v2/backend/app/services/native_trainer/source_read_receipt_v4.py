"""Truthful, standalone source-read receipt v4 for closed intervals.

The v3 receipt schema has one ambiguous ``event_time`` and requires it to be
no later than both ``feature_cutoff`` and ``finality_cutoff``.  That cannot
represent a valid closed Binance websocket candle whose producer message is
observed after the economic candle close.  This deliberately unwired v4
primitive separates those clocks:

* ``economic_event_time`` is the closed interval's economic close;
* ``producer_event_time`` is the producer message timestamp;
* ``ingested_at`` is the producer/ingestor observation timestamp;
* ``available_at`` is when the exact source value became available;
* ``consumer_observed_at`` is the downstream exact-read completion clock.

Only ``CLOSED_INTERVAL`` direct reads are supported by this P0-A schema.  No
ledger accepts the result, and no feature publication, trainer, prediction,
paper-trading, or live-execution path imports this module.  Every downstream
authorization flag is both frozen false on the returned value and hashed false
inside the canonical receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, NoReturn, cast

SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION = "feature_source_consumer_read_receipt_v4"
SOURCE_READ_EVIDENCE_V4_SCHEMA_VERSION = "feature_source_exact_read_evidence_v4"
SOURCE_FINALITY_EVIDENCE_V4_SCHEMA_VERSION = "feature_source_finality_evidence_v4"
SOURCE_READ_LOCATOR_V4_SCHEMA_VERSION = "feature_source_read_locator_v4"
SOURCE_READ_RECEIPT_V4_EVIDENCE_CLASSIFICATION = (
    "TRUTHFUL_CLOSED_INTERVAL_SOURCE_RECEIPT_V4_STANDALONE_UNWIRED"
)
SOURCE_READ_RECEIPT_V4_DOWNSTREAM_STATUS = (
    "NO_LEDGER_APPEND_FEATURE_PUBLICATION_TRAINER_OR_EXECUTION_AUTHORIZATION"
)
SOURCE_READ_RECEIPT_V4_KIND = "DIRECT_READ"
SOURCE_READ_RECEIPT_V4_FINALITY_TYPE = "CLOSED_INTERVAL"

# Resource-integrity ceilings only; they do not select a market or observation.
MAX_SOURCE_RECEIPT_V4_BYTES = 64 * 1024
MAX_SOURCE_PAYLOAD_BYTES = 256 * 1024 * 1024
MAX_LABEL_BYTES = 256
MAX_LOCATOR_BYTES = 2 * 1024

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$",
    re.ASCII,
)
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@-]{0,255}$", re.ASCII)
_LOCATOR_RE = re.compile(r"^[\x20-\x7e]{1,2048}$", re.ASCII)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_CONSTRUCTION_TOKEN = object()

_DOWNSTREAM_FLAG_FIELDS = (
    "durable_ledger_appended",
    "feature_snapshot_published",
    "feature_publication_receipt_emitted",
    "consumer_eligible",
    "trainer_admission_granted",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
)
_CLOCK_FIELDS = (
    "economic_event_time",
    "producer_event_time",
    "ingested_at",
    "available_at",
    "consumer_observed_at",
    "feature_cutoff",
)
_READ_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "source_label",
        "payload_type",
        "payload_sha256",
        "payload_byte_count",
        "economic_event_time",
        "producer_event_time",
        "ingested_at",
        "available_at",
        "read_locator_type",
        "read_locator",
        "read_locator_version",
        "read_locator_sha256",
        "read_completed_at",
    }
)
_FINALITY_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "source_label",
        "payload_type",
        "payload_sha256",
        "payload_byte_count",
        "read_evidence_sha256",
        "read_locator_sha256",
        "economic_event_time",
        "producer_event_time",
        "ingested_at",
        "available_at",
        "consumer_observed_at",
        "finality_type",
        "event_final",
        "finality_cutoff",
        "finality_verified_at",
        "verifier",
    }
)
_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "downstream_status",
        "receipt_kind",
        "source_label",
        "payload_type",
        "payload_sha256",
        "payload_byte_count",
        *_CLOCK_FIELDS,
        "read_evidence",
        "read_evidence_sha256",
        "read_locator_sha256",
        "finality_evidence",
        "finality_evidence_sha256",
        *_DOWNSTREAM_FLAG_FIELDS,
        "receipt_sha256",
    }
)
_READ_LOCATOR_TYPES = frozenset(
    {
        "FILE_CONTENT_ADDRESS",
        "HTTP_RESPONSE_DIGEST",
        "IN_MEMORY_IMMUTABLE_OBJECT",
        "REDIS_VERSIONED_VALUE",
        "SQLITE_IMMUTABLE_ROW",
        "WEBSOCKET_EVENT_DIGEST",
    }
)


class SourceReadReceiptV4Error(RuntimeError):
    """Base error for the standalone v4 receipt boundary."""


class SourceReadReceiptV4ValidationError(SourceReadReceiptV4Error):
    """Receipt input, clocks, evidence, or hashes fail closed."""

    def __init__(self, reasons: tuple[str, ...] | list[str]) -> None:
        unique_reasons = tuple(dict.fromkeys(reasons))
        self.reasons = unique_reasons
        super().__init__(";".join(unique_reasons))


@dataclass(frozen=True, slots=True)
class SourceReadReceiptV4:
    """Frozen canonical receipt whose mapping property returns fresh copies."""

    schema_version: str
    receipt_sha256: str
    receipt_json: str = field(repr=False)
    _construction_token: object = field(repr=False, compare=False)
    durable_ledger_appended: bool = field(default=False, init=False)
    feature_snapshot_published: bool = field(default=False, init=False)
    feature_publication_receipt_emitted: bool = field(default=False, init=False)
    consumer_eligible: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    prediction_authorized: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _raise(["SOURCE_RECEIPT_V4_FACTORY_CONSTRUCTION_REQUIRED"])
        if self.schema_version != SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION:
            _raise(["SOURCE_RECEIPT_V4_ARTIFACT_SCHEMA_MISMATCH"])
        receipt = _parse_receipt_json(self.receipt_json)
        validated = _validated_receipt_mapping(receipt)
        if (
            validated["receipt_sha256"] != self.receipt_sha256
            or _canonical_json(validated) != self.receipt_json
        ):
            _raise(["SOURCE_RECEIPT_V4_ARTIFACT_BINDING_MISMATCH"])

    @property
    def receipt(self) -> dict[str, Any]:
        """Return a freshly parsed and fully revalidated exact mapping."""

        receipt = _parse_receipt_json(self.receipt_json)
        validated = _validated_receipt_mapping(receipt)
        return cast(dict[str, Any], json.loads(_canonical_json(validated)))


def _raise(reasons: list[str]) -> NoReturn:
    raise SourceReadReceiptV4ValidationError(reasons) from None


def _canonical_json(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError, RecursionError):
        _raise(["SOURCE_RECEIPT_V4_NOT_STRICT_JSON"])
    if len(encoded.encode("ascii")) > MAX_SOURCE_RECEIPT_V4_BYTES:
        _raise(["SOURCE_RECEIPT_V4_SIZE_LIMIT_EXCEEDED"])
    return encoded


def _stable_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("ascii")).hexdigest()


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _raise(["SOURCE_RECEIPT_V4_DUPLICATE_JSON_KEY"])
        result[key] = value
    return result


def _parse_receipt_json(value: object) -> dict[str, Any]:
    if type(value) is not str:
        _raise(["SOURCE_RECEIPT_V4_ARTIFACT_JSON_INVALID"])
    if not value or len(value) > MAX_SOURCE_RECEIPT_V4_BYTES:
        _raise(["SOURCE_RECEIPT_V4_ARTIFACT_JSON_INVALID"])
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        _raise(["SOURCE_RECEIPT_V4_ARTIFACT_JSON_INVALID"])
    if len(encoded) > MAX_SOURCE_RECEIPT_V4_BYTES:
        _raise(["SOURCE_RECEIPT_V4_ARTIFACT_JSON_INVALID"])
    try:
        decoded = json.loads(
            value,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=lambda _: _raise(["SOURCE_RECEIPT_V4_JSON_CONSTANT_FORBIDDEN"]),
        )
    except SourceReadReceiptV4ValidationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError, OverflowError, RecursionError):
        _raise(["SOURCE_RECEIPT_V4_ARTIFACT_JSON_INVALID"])
    if type(decoded) is not dict:
        _raise(["SOURCE_RECEIPT_V4_NOT_EXACT_OBJECT"])
    return cast(dict[str, Any], decoded)


def _snapshot_exact_dict(
    value: object,
    *,
    expected_fields: frozenset[str],
    object_reason: str,
    field_reason: str,
) -> dict[str, Any]:
    if type(value) is not dict:
        _raise([object_reason])
    source = cast(dict[object, object], value)
    try:
        pairs = tuple(source.items())
    except RuntimeError:
        _raise([f"{object_reason}_MUTATED"])
    if len(pairs) != len(source):
        _raise([f"{object_reason}_MUTATED"])
    copied: dict[str, Any] = {}
    for key, item in pairs:
        if type(key) is not str:
            _raise([field_reason])
        copied[key] = item
    if frozenset(copied) != expected_fields:
        _raise([field_reason])
    return copied


def _valid_label(value: object) -> bool:
    return (
        type(value) is str
        and len(value) <= MAX_LABEL_BYTES
        and value.isascii()
        and len(value.encode("ascii")) <= MAX_LABEL_BYTES
        and _LABEL_RE.fullmatch(value) is not None
    )


def _valid_locator(value: object) -> bool:
    return (
        type(value) is str
        and len(value) <= MAX_LOCATOR_BYTES
        and value.isascii()
        and len(value.encode("ascii")) <= MAX_LOCATOR_BYTES
        and _LOCATOR_RE.fullmatch(value) is not None
        and value == value.strip()
    )


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _parse_clock(value: object) -> datetime | None:
    if type(value) is not str or _CLOCK_RE.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    if parsed < _EPOCH:
        return None
    canonical = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return parsed if canonical == value else None


def _required_label(value: object, *, reason: str) -> str:
    if not _valid_label(value):
        _raise([reason])
    return cast(str, value)


def _required_locator(value: object, *, reason: str) -> str:
    if not _valid_locator(value):
        _raise([reason])
    return cast(str, value)


def _required_sha256(value: object, *, reason: str) -> str:
    if not _valid_sha256(value):
        _raise([reason])
    return cast(str, value)


def _required_payload_count(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_SOURCE_PAYLOAD_BYTES:
        _raise(["SOURCE_RECEIPT_V4_PAYLOAD_BYTE_COUNT_INVALID"])
    return value


def _required_clock(value: object, *, reason: str) -> tuple[str, datetime]:
    parsed = _parse_clock(value)
    if parsed is None:
        _raise([reason])
    return cast(str, value), parsed


def _clock_order_reasons(clocks: dict[str, datetime]) -> list[str]:
    reasons: list[str] = []
    ordered_pairs = (
        (
            "economic_event_time",
            "producer_event_time",
            "SOURCE_PRODUCER_EVENT_TIME_BEFORE_ECONOMIC_EVENT_TIME",
        ),
        (
            "producer_event_time",
            "ingested_at",
            "SOURCE_PRODUCER_EVENT_TIME_AFTER_INGESTED_AT",
        ),
        ("ingested_at", "available_at", "SOURCE_INGESTED_AT_AFTER_AVAILABLE_AT"),
        (
            "available_at",
            "consumer_observed_at",
            "SOURCE_AVAILABLE_AT_AFTER_CONSUMER_OBSERVED_AT",
        ),
        (
            "economic_event_time",
            "feature_cutoff",
            "SOURCE_ECONOMIC_EVENT_TIME_AFTER_FEATURE_CUTOFF",
        ),
        (
            "feature_cutoff",
            "consumer_observed_at",
            "SOURCE_FEATURE_CUTOFF_AFTER_CONSUMER_OBSERVED_AT",
        ),
    )
    for earlier, later, reason in ordered_pairs:
        if clocks[earlier] > clocks[later]:
            reasons.append(reason)
    return reasons


def _builder_clocks(
    *,
    economic_event_time: object,
    producer_event_time: object,
    ingested_at: object,
    available_at: object,
    consumer_observed_at: object,
    feature_cutoff: object,
    finality_cutoff: object,
    finality_verified_at: object,
) -> tuple[dict[str, str], dict[str, datetime]]:
    values = {
        "economic_event_time": economic_event_time,
        "producer_event_time": producer_event_time,
        "ingested_at": ingested_at,
        "available_at": available_at,
        "consumer_observed_at": consumer_observed_at,
        "feature_cutoff": feature_cutoff,
        "finality_cutoff": finality_cutoff,
        "finality_verified_at": finality_verified_at,
    }
    canonical: dict[str, str] = {}
    parsed: dict[str, datetime] = {}
    for field_name, value in values.items():
        canonical[field_name], parsed[field_name] = _required_clock(
            value,
            reason=f"SOURCE_RECEIPT_V4_{field_name.upper()}_INVALID",
        )
    reasons = _clock_order_reasons(parsed)
    if parsed["finality_cutoff"] != parsed["economic_event_time"]:
        reasons.append("SOURCE_CLOSED_INTERVAL_FINALITY_CUTOFF_MISMATCH")
    if parsed["available_at"] > parsed["finality_verified_at"]:
        reasons.append("SOURCE_AVAILABLE_AT_AFTER_FINALITY_VERIFIED_AT")
    if parsed["finality_verified_at"] > parsed["consumer_observed_at"]:
        reasons.append("SOURCE_FINALITY_VERIFIED_AT_AFTER_CONSUMER_OBSERVED_AT")
    if reasons:
        _raise(reasons)
    return canonical, parsed


def _validated_receipt_mapping(receipt: object) -> dict[str, Any]:
    root = _snapshot_exact_dict(
        receipt,
        expected_fields=_RECEIPT_FIELDS,
        object_reason="SOURCE_RECEIPT_V4_NOT_EXACT_OBJECT",
        field_reason="SOURCE_RECEIPT_V4_FIELD_SET_MISMATCH",
    )
    read_evidence = _snapshot_exact_dict(
        root["read_evidence"],
        expected_fields=_READ_EVIDENCE_FIELDS,
        object_reason="SOURCE_READ_EVIDENCE_V4_NOT_EXACT_OBJECT",
        field_reason="SOURCE_READ_EVIDENCE_V4_FIELD_SET_MISMATCH",
    )
    finality_evidence = _snapshot_exact_dict(
        root["finality_evidence"],
        expected_fields=_FINALITY_EVIDENCE_FIELDS,
        object_reason="SOURCE_FINALITY_EVIDENCE_V4_NOT_EXACT_OBJECT",
        field_reason="SOURCE_FINALITY_EVIDENCE_V4_FIELD_SET_MISMATCH",
    )
    normalized = {**root, "read_evidence": read_evidence, "finality_evidence": finality_evidence}
    reasons: list[str] = []

    if root["schema_version"] != SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION:
        reasons.append("SOURCE_RECEIPT_V4_SCHEMA_VERSION_MISMATCH")
    if root["evidence_classification"] != SOURCE_READ_RECEIPT_V4_EVIDENCE_CLASSIFICATION:
        reasons.append("SOURCE_RECEIPT_V4_EVIDENCE_CLASSIFICATION_MISMATCH")
    if root["downstream_status"] != SOURCE_READ_RECEIPT_V4_DOWNSTREAM_STATUS:
        reasons.append("SOURCE_RECEIPT_V4_DOWNSTREAM_STATUS_MISMATCH")
    if root["receipt_kind"] != SOURCE_READ_RECEIPT_V4_KIND:
        reasons.append("SOURCE_RECEIPT_V4_KIND_INVALID")
    for field_name in _DOWNSTREAM_FLAG_FIELDS:
        if root[field_name] is not False:
            reasons.append(f"SOURCE_RECEIPT_V4_{field_name.upper()}_MUST_BE_FALSE")
    for field_name in ("source_label", "payload_type"):
        if not _valid_label(root[field_name]):
            reasons.append(f"SOURCE_RECEIPT_V4_{field_name.upper()}_INVALID")
    if not _valid_sha256(root["payload_sha256"]):
        reasons.append("SOURCE_RECEIPT_V4_PAYLOAD_SHA256_INVALID")
    if (
        type(root["payload_byte_count"]) is not int
        or not 1 <= root["payload_byte_count"] <= MAX_SOURCE_PAYLOAD_BYTES
    ):
        reasons.append("SOURCE_RECEIPT_V4_PAYLOAD_BYTE_COUNT_INVALID")

    parsed_clocks: dict[str, datetime] = {}
    for field_name in _CLOCK_FIELDS:
        parsed = _parse_clock(root[field_name])
        if parsed is None:
            reasons.append(f"SOURCE_RECEIPT_V4_{field_name.upper()}_INVALID")
        else:
            parsed_clocks[field_name] = parsed
    if len(parsed_clocks) == len(_CLOCK_FIELDS):
        reasons.extend(_clock_order_reasons(parsed_clocks))

    if read_evidence["schema_version"] != SOURCE_READ_EVIDENCE_V4_SCHEMA_VERSION:
        reasons.append("SOURCE_READ_EVIDENCE_V4_SCHEMA_VERSION_MISMATCH")
    for field_name in ("source_label", "payload_type", "payload_sha256", "payload_byte_count"):
        if read_evidence[field_name] != root[field_name]:
            reasons.append(f"SOURCE_READ_EVIDENCE_V4_{field_name.upper()}_BINDING_MISMATCH")
    for field_name in (
        "economic_event_time",
        "producer_event_time",
        "ingested_at",
        "available_at",
    ):
        if read_evidence[field_name] != root[field_name]:
            reasons.append(f"SOURCE_READ_EVIDENCE_V4_{field_name.upper()}_BINDING_MISMATCH")
    if read_evidence["read_completed_at"] != root["consumer_observed_at"]:
        reasons.append("SOURCE_READ_EVIDENCE_V4_COMPLETION_CLOCK_BINDING_MISMATCH")
    if (
        type(read_evidence["read_locator_type"]) is not str
        or read_evidence["read_locator_type"] not in _READ_LOCATOR_TYPES
    ):
        reasons.append("SOURCE_READ_EVIDENCE_V4_LOCATOR_TYPE_INVALID")
    if not _valid_locator(read_evidence["read_locator"]):
        reasons.append("SOURCE_READ_EVIDENCE_V4_LOCATOR_INVALID")
    if not _valid_label(read_evidence["read_locator_version"]):
        reasons.append("SOURCE_READ_EVIDENCE_V4_LOCATOR_VERSION_INVALID")
    locator_material = {
        "schema_version": SOURCE_READ_LOCATOR_V4_SCHEMA_VERSION,
        "read_locator_type": read_evidence["read_locator_type"],
        "read_locator": read_evidence["read_locator"],
        "read_locator_version": read_evidence["read_locator_version"],
    }
    expected_locator_sha256 = _stable_sha256(locator_material)
    if read_evidence["read_locator_sha256"] != expected_locator_sha256:
        reasons.append("SOURCE_READ_EVIDENCE_V4_LOCATOR_SHA256_MISMATCH")
    if root["read_locator_sha256"] != expected_locator_sha256:
        reasons.append("SOURCE_RECEIPT_V4_LOCATOR_SHA256_MISMATCH")
    expected_read_sha256 = _stable_sha256(read_evidence)
    if root["read_evidence_sha256"] != expected_read_sha256:
        reasons.append("SOURCE_READ_EVIDENCE_V4_SHA256_MISMATCH")

    if finality_evidence["schema_version"] != SOURCE_FINALITY_EVIDENCE_V4_SCHEMA_VERSION:
        reasons.append("SOURCE_FINALITY_EVIDENCE_V4_SCHEMA_VERSION_MISMATCH")
    for field_name in ("source_label", "payload_type", "payload_sha256", "payload_byte_count"):
        if finality_evidence[field_name] != root[field_name]:
            reasons.append(f"SOURCE_FINALITY_EVIDENCE_V4_{field_name.upper()}_BINDING_MISMATCH")
    for field_name in (
        "economic_event_time",
        "producer_event_time",
        "ingested_at",
        "available_at",
        "consumer_observed_at",
    ):
        if finality_evidence[field_name] != root[field_name]:
            reasons.append(f"SOURCE_FINALITY_EVIDENCE_V4_{field_name.upper()}_BINDING_MISMATCH")
    if finality_evidence["read_evidence_sha256"] != expected_read_sha256:
        reasons.append("SOURCE_FINALITY_EVIDENCE_V4_READ_SHA256_BINDING_MISMATCH")
    if finality_evidence["read_locator_sha256"] != expected_locator_sha256:
        reasons.append("SOURCE_FINALITY_EVIDENCE_V4_LOCATOR_SHA256_BINDING_MISMATCH")
    if finality_evidence["finality_type"] != SOURCE_READ_RECEIPT_V4_FINALITY_TYPE:
        reasons.append("SOURCE_FINALITY_EVIDENCE_V4_TYPE_INVALID")
    if finality_evidence["event_final"] is not True:
        reasons.append("SOURCE_FINALITY_EVIDENCE_V4_NOT_FINAL")
    if not _valid_label(finality_evidence["verifier"]):
        reasons.append("SOURCE_FINALITY_EVIDENCE_V4_VERIFIER_INVALID")
    finality_cutoff = _parse_clock(finality_evidence["finality_cutoff"])
    finality_verified_at = _parse_clock(finality_evidence["finality_verified_at"])
    if finality_cutoff is None:
        reasons.append("SOURCE_FINALITY_EVIDENCE_V4_CUTOFF_INVALID")
    if finality_verified_at is None:
        reasons.append("SOURCE_FINALITY_EVIDENCE_V4_VERIFIED_AT_INVALID")
    economic_event = parsed_clocks.get("economic_event_time")
    available = parsed_clocks.get("available_at")
    consumer_observed = parsed_clocks.get("consumer_observed_at")
    if finality_cutoff is not None and economic_event is not None:
        if finality_cutoff != economic_event:
            reasons.append("SOURCE_CLOSED_INTERVAL_FINALITY_CUTOFF_MISMATCH")
    if finality_verified_at is not None and available is not None:
        if available > finality_verified_at:
            reasons.append("SOURCE_AVAILABLE_AT_AFTER_FINALITY_VERIFIED_AT")
    if finality_verified_at is not None and consumer_observed is not None:
        if finality_verified_at > consumer_observed:
            reasons.append("SOURCE_FINALITY_VERIFIED_AT_AFTER_CONSUMER_OBSERVED_AT")
    expected_finality_sha256 = _stable_sha256(finality_evidence)
    if root["finality_evidence_sha256"] != expected_finality_sha256:
        reasons.append("SOURCE_FINALITY_EVIDENCE_V4_SHA256_MISMATCH")

    material_without_receipt_hash = {
        key: value for key, value in normalized.items() if key != "receipt_sha256"
    }
    expected_receipt_sha256 = _stable_sha256(material_without_receipt_hash)
    if root["receipt_sha256"] != expected_receipt_sha256:
        reasons.append("SOURCE_RECEIPT_V4_SHA256_MISMATCH")
    if reasons:
        _raise(reasons)
    if len(_canonical_json(normalized).encode("ascii")) > MAX_SOURCE_RECEIPT_V4_BYTES:
        _raise(["SOURCE_RECEIPT_V4_SIZE_LIMIT_EXCEEDED"])
    return normalized


def validate_source_read_receipt_v4(receipt: object) -> SourceReadReceiptV4:
    """Validate and freeze one exact v4 direct closed-interval receipt."""

    validated = _validated_receipt_mapping(receipt)
    return SourceReadReceiptV4(
        schema_version=SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION,
        receipt_sha256=cast(str, validated["receipt_sha256"]),
        receipt_json=_canonical_json(validated),
        _construction_token=_CONSTRUCTION_TOKEN,
    )


def build_source_read_receipt_v4(
    *,
    source_label: str,
    payload_type: str,
    payload_sha256: str,
    payload_byte_count: int,
    economic_event_time: str,
    producer_event_time: str,
    ingested_at: str,
    available_at: str,
    consumer_observed_at: str,
    feature_cutoff: str,
    read_locator_type: str,
    read_locator: str,
    read_locator_version: str,
    finality_type: str,
    finality_cutoff: str,
    finality_verified_at: str,
    finality_verifier: str,
) -> SourceReadReceiptV4:
    """Build a truthful, hashed, still-unwired direct closed-interval receipt."""

    label = _required_label(source_label, reason="SOURCE_RECEIPT_V4_SOURCE_LABEL_INVALID")
    exact_payload_type = _required_label(
        payload_type,
        reason="SOURCE_RECEIPT_V4_PAYLOAD_TYPE_INVALID",
    )
    exact_payload_sha256 = _required_sha256(
        payload_sha256,
        reason="SOURCE_RECEIPT_V4_PAYLOAD_SHA256_INVALID",
    )
    exact_payload_count = _required_payload_count(payload_byte_count)
    if type(read_locator_type) is not str or read_locator_type not in _READ_LOCATOR_TYPES:
        _raise(["SOURCE_READ_EVIDENCE_V4_LOCATOR_TYPE_INVALID"])
    locator = _required_locator(
        read_locator,
        reason="SOURCE_READ_EVIDENCE_V4_LOCATOR_INVALID",
    )
    locator_version = _required_label(
        read_locator_version,
        reason="SOURCE_READ_EVIDENCE_V4_LOCATOR_VERSION_INVALID",
    )
    if finality_type != SOURCE_READ_RECEIPT_V4_FINALITY_TYPE:
        _raise(["SOURCE_FINALITY_EVIDENCE_V4_TYPE_INVALID"])
    verifier = _required_label(
        finality_verifier,
        reason="SOURCE_FINALITY_EVIDENCE_V4_VERIFIER_INVALID",
    )
    clocks, _ = _builder_clocks(
        economic_event_time=economic_event_time,
        producer_event_time=producer_event_time,
        ingested_at=ingested_at,
        available_at=available_at,
        consumer_observed_at=consumer_observed_at,
        feature_cutoff=feature_cutoff,
        finality_cutoff=finality_cutoff,
        finality_verified_at=finality_verified_at,
    )

    locator_material = {
        "schema_version": SOURCE_READ_LOCATOR_V4_SCHEMA_VERSION,
        "read_locator_type": read_locator_type,
        "read_locator": locator,
        "read_locator_version": locator_version,
    }
    read_locator_sha256 = _stable_sha256(locator_material)
    read_evidence: dict[str, Any] = {
        "schema_version": SOURCE_READ_EVIDENCE_V4_SCHEMA_VERSION,
        "source_label": label,
        "payload_type": exact_payload_type,
        "payload_sha256": exact_payload_sha256,
        "payload_byte_count": exact_payload_count,
        "economic_event_time": clocks["economic_event_time"],
        "producer_event_time": clocks["producer_event_time"],
        "ingested_at": clocks["ingested_at"],
        "available_at": clocks["available_at"],
        "read_locator_type": read_locator_type,
        "read_locator": locator,
        "read_locator_version": locator_version,
        "read_locator_sha256": read_locator_sha256,
        "read_completed_at": clocks["consumer_observed_at"],
    }
    read_evidence_sha256 = _stable_sha256(read_evidence)
    finality_evidence: dict[str, Any] = {
        "schema_version": SOURCE_FINALITY_EVIDENCE_V4_SCHEMA_VERSION,
        "source_label": label,
        "payload_type": exact_payload_type,
        "payload_sha256": exact_payload_sha256,
        "payload_byte_count": exact_payload_count,
        "read_evidence_sha256": read_evidence_sha256,
        "read_locator_sha256": read_locator_sha256,
        "economic_event_time": clocks["economic_event_time"],
        "producer_event_time": clocks["producer_event_time"],
        "ingested_at": clocks["ingested_at"],
        "available_at": clocks["available_at"],
        "consumer_observed_at": clocks["consumer_observed_at"],
        "finality_type": SOURCE_READ_RECEIPT_V4_FINALITY_TYPE,
        "event_final": True,
        "finality_cutoff": clocks["finality_cutoff"],
        "finality_verified_at": clocks["finality_verified_at"],
        "verifier": verifier,
    }
    receipt: dict[str, Any] = {
        "schema_version": SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION,
        "evidence_classification": SOURCE_READ_RECEIPT_V4_EVIDENCE_CLASSIFICATION,
        "downstream_status": SOURCE_READ_RECEIPT_V4_DOWNSTREAM_STATUS,
        "receipt_kind": SOURCE_READ_RECEIPT_V4_KIND,
        "source_label": label,
        "payload_type": exact_payload_type,
        "payload_sha256": exact_payload_sha256,
        "payload_byte_count": exact_payload_count,
        **{field_name: clocks[field_name] for field_name in _CLOCK_FIELDS},
        "read_evidence": read_evidence,
        "read_evidence_sha256": read_evidence_sha256,
        "read_locator_sha256": read_locator_sha256,
        "finality_evidence": finality_evidence,
        "finality_evidence_sha256": _stable_sha256(finality_evidence),
        **{field_name: False for field_name in _DOWNSTREAM_FLAG_FIELDS},
    }
    receipt["receipt_sha256"] = _stable_sha256(receipt)
    return validate_source_read_receipt_v4(receipt)


__all__ = [
    "MAX_SOURCE_PAYLOAD_BYTES",
    "MAX_SOURCE_RECEIPT_V4_BYTES",
    "SOURCE_FINALITY_EVIDENCE_V4_SCHEMA_VERSION",
    "SOURCE_READ_EVIDENCE_V4_SCHEMA_VERSION",
    "SOURCE_READ_LOCATOR_V4_SCHEMA_VERSION",
    "SOURCE_READ_RECEIPT_V4_DOWNSTREAM_STATUS",
    "SOURCE_READ_RECEIPT_V4_EVIDENCE_CLASSIFICATION",
    "SOURCE_READ_RECEIPT_V4_FINALITY_TYPE",
    "SOURCE_READ_RECEIPT_V4_KIND",
    "SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION",
    "SourceReadReceiptV4",
    "SourceReadReceiptV4Error",
    "SourceReadReceiptV4ValidationError",
    "build_source_read_receipt_v4",
    "validate_source_read_receipt_v4",
]
