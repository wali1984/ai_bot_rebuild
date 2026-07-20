"""Non-authoritative canonical feature-value resolver shadow.

The resolver consumes caller-supplied source-record snapshots only.  It never
reads Redis or a provider and it cannot publish, populate TensorBuilder, admit
training data, authorize prediction, or authorize paper/live execution.  Its
purpose is to make the exact branch that *would* be selected inspectable before
any runtime wiring exists.

Every branch comes from :data:`FEATURE_RESOLUTION_PLAN_V4`; callers cannot add
keys, paths, aliases, transforms, providers, or fallback order.  Missing values
remain ``None``.  An observed numeric zero is a resolved measurement and is
therefore distinct from an absent or typed-negative value.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.feature_resolution_plan_v4 import (
    CANONICAL_SOURCE_RECORD_V4_SCHEMA_VERSION,
    FEATURE_RESOLUTION_PLAN_V4,
    FEATURE_RESOLUTION_PLAN_V4_SHA256,
    PLAN_RESOLVABLE,
    TRANSFORM_BOOL,
    TRANSFORM_COMPLEMENT_RATIO,
    TRANSFORM_IDENTITY,
    TRANSFORM_NONNEGATIVE_DIFFERENCE,
    TRANSFORM_RATIO,
    FeatureResolutionBranchPlanV4,
    FeatureSlotResolutionPlanV4,
    materialize_feature_source_key_v4,
    materialize_feature_source_timeframe_v4,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
)

CANONICAL_FEATURE_VALUE_RESOLVER_V4_SCHEMA_VERSION: Final = (
    "canonical_feature_value_resolver_shadow_v4"
)
CANONICAL_FEATURE_VALUE_RESOLVER_V4_EVIDENCE_CLASSIFICATION: Final = (
    "AUDIT_ONLY_CALLER_SUPPLIED_SOURCE_RECORD_RESOLUTION_UNAUTHENTICATED_UNWIRED"
)
CANONICAL_FEATURE_VALUE_RESOLVER_V4_DOWNSTREAM_STATUS: Final = (
    "NON_AUTHORITATIVE_CANNOT_GRANT_TENSOR_TRAINER_PREDICTION_PAPER_OR_LIVE_ELIGIBILITY"
)
CANONICAL_FEATURE_VALUE_RESOLVER_V4_VERSION: Final = "canonical_feature_value_resolver_v4"

RESOLUTION_RESOLVED_MEASURED: Final = "RESOLVED_MEASURED"
RESOLUTION_PLAN_UNRESOLVED: Final = "PLAN_UNRESOLVED"
RESOLUTION_MISSING_SOURCE_RECORD: Final = "MISSING_SOURCE_RECORD"
RESOLUTION_MISSING_PATH: Final = "MISSING_PATH"
RESOLUTION_MISSING_NULL: Final = "MISSING_NULL"
RESOLUTION_SOURCE_RECORD_REJECTED: Final = "SOURCE_RECORD_REJECTED"
RESOLUTION_VALUE_REJECTED: Final = "VALUE_REJECTED"
RESOLUTION_EMPTY_COLLECTION_RECEIPT_REQUIRED: Final = (
    "EMPTY_COLLECTION_AUTHENTICATED_RECEIPT_REQUIRED"
)
RESOLUTION_TYPED_NEGATIVE_RECEIPT_REQUIRED: Final = "TYPED_NEGATIVE_AUTHENTICATED_RECEIPT_REQUIRED"
RESOLUTION_COLLECTION_TRANSFORM_UNWIRED: Final = "COLLECTION_TRANSFORM_UNWIRED"

_RESOLUTION_STATUSES: Final = frozenset(
    {
        RESOLUTION_RESOLVED_MEASURED,
        RESOLUTION_PLAN_UNRESOLVED,
        RESOLUTION_MISSING_SOURCE_RECORD,
        RESOLUTION_MISSING_PATH,
        RESOLUTION_MISSING_NULL,
        RESOLUTION_SOURCE_RECORD_REJECTED,
        RESOLUTION_VALUE_REJECTED,
        RESOLUTION_EMPTY_COLLECTION_RECEIPT_REQUIRED,
        RESOLUTION_TYPED_NEGATIVE_RECEIPT_REQUIRED,
        RESOLUTION_COLLECTION_TRANSFORM_UNWIRED,
    }
)

_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$",
    re.ASCII,
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,32}$", re.ASCII)
_TIMEFRAME_RE = re.compile(r"^[1-9][0-9]{0,5}[mhdw]$", re.ASCII)
_CONSTRUCTION_TOKEN = object()

_SOURCE_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "payload_schema_version",
        "source_label",
        "source_key",
        "source_record_id",
        "source_record_sha256",
        "symbol",
        "request_timeframe",
        "source_timeframe",
        "payload",
        "payload_sha256",
        "event_time",
        "ingested_at",
        "source_available_at",
        "feature_cutoff",
        "generated_at",
        "publication_available_at",
        "candle_close_time",
        "candle_final",
        "absence_receipt",
    }
)
_AUTHORIZATION_FIELDS = (
    "tensor_eligible",
    "trainer_admission_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
)


class CanonicalFeatureValueResolverV4Error(ValueError):
    """Input or a shadow result violates the closed resolver contract."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise CanonicalFeatureValueResolverV4Error(*reasons) from None


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("CANONICAL_FEATURE_RESOLVER_V4_STRICT_JSON_REQUIRED")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("ascii")).hexdigest()


def canonical_source_payload_sha256_v4(payload: object) -> str:
    """Digest exact strict-JSON payload semantics for a shadow source record."""

    return _sha256(payload)


def canonical_source_record_id_v4(
    *,
    source_label: str,
    source_key: str,
    symbol: str,
    request_timeframe: str,
    source_timeframe: str | None,
) -> str:
    """Bind the complete semantic locator, not merely a colliding physical key."""

    if (
        type(source_label) is not str
        or type(source_key) is not str
        or type(symbol) is not str
        or _SYMBOL_RE.fullmatch(symbol) is None
        or type(request_timeframe) is not str
        or _TIMEFRAME_RE.fullmatch(request_timeframe) is None
        or (
            source_timeframe is not None
            and (
                type(source_timeframe) is not str
                or _TIMEFRAME_RE.fullmatch(source_timeframe) is None
            )
        )
    ):
        _fail("CANONICAL_FEATURE_RESOLVER_V4_SOURCE_RECORD_IDENTITY_INVALID")
    return _sha256(
        {
            "schema_version": CANONICAL_SOURCE_RECORD_V4_SCHEMA_VERSION,
            "source_label": source_label,
            "source_key": source_key,
            "symbol": symbol,
            "request_timeframe": request_timeframe,
            "source_timeframe": source_timeframe,
        }
    )


def canonical_source_record_sha256_v4(record: dict[str, object]) -> str:
    """Digest the complete source envelope, excluding its digest field."""

    if type(record) is not dict:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_SOURCE_RECORD_NOT_EXACT_DICT")
    material = {key: value for key, value in record.items() if key != "source_record_sha256"}
    return _sha256(material)


def _parse_clock(value: object) -> datetime | None:
    if type(value) is not str or _CLOCK_RE.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    canonical = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return parsed if parsed >= _EPOCH and canonical == value else None


def _canonical_float32(value: object) -> tuple[float | None, str | None]:
    if type(value) not in (int, float) or isinstance(value, bool):
        return None, "VALUE_NOT_EXACT_FINITE_NUMBER"
    try:
        parsed = float(cast(int | float, value))
        runtime = float(struct.unpack("!f", struct.pack("!f", parsed))[0])
    except (OverflowError, struct.error, TypeError, ValueError):
        return None, "VALUE_NOT_FLOAT32_REPRESENTABLE"
    if not math.isfinite(parsed) or not math.isfinite(runtime):
        return None, "VALUE_NOT_EXACT_FINITE_NUMBER"
    if parsed != 0.0 and runtime == 0.0:
        return None, "VALUE_FLOAT32_UNDERFLOW"
    return (0.0 if runtime == 0.0 else runtime), None


def _float32_hex(value: float) -> str:
    return struct.pack("!f", value).hex()


@dataclass(frozen=True, slots=True)
class FeatureValueResolutionAuditV4:
    """Frozen result for one slot; every authority bit is fixed false."""

    result_json: str = field(repr=False)
    result_sha256: str
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("CANONICAL_FEATURE_RESOLVER_V4_FACTORY_CONSTRUCTION_REQUIRED")
        _validate_result_binding(self.result_json, self.result_sha256)

    @property
    def result(self) -> dict[str, Any]:
        """Return a detached mapping after rechecking the result hash."""

        return _validate_result_binding(self.result_json, self.result_sha256)

    @property
    def audit_only(self) -> bool:
        return True

    @property
    def runtime_wired(self) -> bool:
        return False

    @property
    def tensor_eligible(self) -> bool:
        return False

    @property
    def trainer_admission_authorized(self) -> bool:
        return False

    @property
    def prediction_authorized(self) -> bool:
        return False

    @property
    def paper_trading_authorized(self) -> bool:
        return False

    @property
    def live_execution_authorized(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class CanonicalFeatureResolutionAuditV4:
    """Frozen 446-slot audit output with no runtime authority."""

    audit_json: str = field(repr=False)
    audit_sha256: str
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("CANONICAL_FEATURE_RESOLVER_V4_FACTORY_CONSTRUCTION_REQUIRED")
        _validate_audit_binding(self.audit_json, self.audit_sha256)

    @property
    def audit(self) -> dict[str, Any]:
        """Return a detached mapping after rechecking the audit hash."""

        return _validate_audit_binding(self.audit_json, self.audit_sha256)

    @property
    def audit_only(self) -> bool:
        return True

    @property
    def runtime_wired(self) -> bool:
        return False

    @property
    def runtime_source_reads_performed(self) -> bool:
        return False

    @property
    def tensor_eligible(self) -> bool:
        return False

    @property
    def trainer_admission_authorized(self) -> bool:
        return False

    @property
    def prediction_authorized(self) -> bool:
        return False

    @property
    def paper_trading_authorized(self) -> bool:
        return False

    @property
    def live_execution_authorized(self) -> bool:
        return False


def _parse_result(value: object) -> dict[str, Any]:
    if type(value) is not str:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_JSON_INVALID")
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
        _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_JSON_INVALID")
    if type(parsed) is not dict:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_JSON_INVALID")
    return cast(dict[str, Any], parsed)


def _parse_audit(value: object) -> dict[str, Any]:
    return _parse_result(value)


def _validate_request(
    symbol: object, request_timeframe: object, decision_time: object
) -> tuple[str, str, str, datetime]:
    if type(symbol) is not str or _SYMBOL_RE.fullmatch(symbol) is None:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_SYMBOL_INVALID")
    if type(request_timeframe) is not str or _TIMEFRAME_RE.fullmatch(request_timeframe) is None:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_REQUEST_TIMEFRAME_INVALID")
    parsed_decision = _parse_clock(decision_time)
    if parsed_decision is None:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_DECISION_TIME_INVALID")
    return symbol, request_timeframe, cast(str, decision_time), parsed_decision


def _snapshot_source_records(source_records: object) -> dict[str, dict[str, Any]]:
    if type(source_records) is not dict:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_SOURCE_RECORDS_NOT_EXACT_DICT")
    records = cast(dict[object, object], source_records)
    if any(
        type(key) is not str or _SHA256_RE.fullmatch(key) is None or type(value) is not dict
        for key, value in records.items()
    ):
        _fail("CANONICAL_FEATURE_RESOLVER_V4_SOURCE_RECORD_ENTRY_INVALID")
    try:
        encoded = _canonical_json(records)
        decoded = json.loads(encoded)
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
        _fail("CANONICAL_FEATURE_RESOLVER_V4_SOURCE_RECORDS_NOT_STRICT_JSON")
    if type(decoded) is not dict:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_SOURCE_RECORDS_NOT_EXACT_DICT")
    return cast(dict[str, dict[str, Any]], decoded)


def _record_reasons(
    record: dict[str, Any],
    *,
    slot: FeatureSlotResolutionPlanV4,
    expected_key: str,
    expected_record_id: str,
    symbol: str,
    request_timeframe: str,
    source_timeframe: str | None,
    decision_time: datetime,
) -> tuple[tuple[str, ...], dict[str, str]]:
    reasons: list[str] = []
    if frozenset(record) != _SOURCE_RECORD_FIELDS:
        return ("SOURCE_RECORD_FIELD_SET_MISMATCH",), {}
    expected_values = (
        (record.get("schema_version"), CANONICAL_SOURCE_RECORD_V4_SCHEMA_VERSION, "SCHEMA"),
        (
            record.get("payload_schema_version"),
            slot.source_payload_schema_version,
            "PAYLOAD_SCHEMA",
        ),
        (record.get("source_label"), slot.configured_source_label, "SOURCE_LABEL"),
        (record.get("source_key"), expected_key, "SOURCE_KEY"),
        (record.get("source_record_id"), expected_record_id, "SOURCE_RECORD_ID"),
        (record.get("symbol"), symbol, "SYMBOL"),
        (record.get("request_timeframe"), request_timeframe, "REQUEST_TIMEFRAME"),
        (record.get("source_timeframe"), source_timeframe, "SOURCE_TIMEFRAME"),
    )
    for actual, expected, name in expected_values:
        if actual != expected:
            reasons.append(f"SOURCE_RECORD_{name}_MISMATCH")
    payload_sha256 = record.get("payload_sha256")
    if type(payload_sha256) is not str or _SHA256_RE.fullmatch(payload_sha256) is None:
        reasons.append("SOURCE_RECORD_PAYLOAD_SHA256_INVALID")
    else:
        calculated = canonical_source_payload_sha256_v4(record.get("payload"))
        if payload_sha256 != calculated:
            reasons.append("SOURCE_RECORD_PAYLOAD_SHA256_MISMATCH")
    source_record_sha256 = record.get("source_record_sha256")
    if type(source_record_sha256) is not str or _SHA256_RE.fullmatch(source_record_sha256) is None:
        reasons.append("SOURCE_RECORD_SHA256_INVALID")
    elif source_record_sha256 != canonical_source_record_sha256_v4(record):
        reasons.append("SOURCE_RECORD_SHA256_MISMATCH")

    clock_fields = (
        "event_time",
        "ingested_at",
        "source_available_at",
        "feature_cutoff",
        "generated_at",
        "publication_available_at",
    )
    parsed: dict[str, datetime] = {}
    canonical: dict[str, str] = {}
    for name in clock_fields:
        value = record.get(name)
        clock = _parse_clock(value)
        if clock is None:
            reasons.append(f"SOURCE_RECORD_{name.upper()}_INVALID")
        else:
            parsed[name] = clock
            canonical[name] = cast(str, value)
    if len(parsed) == len(clock_fields):
        for earlier, later, reason in (
            ("event_time", "ingested_at", "EVENT_TIME_AFTER_INGESTED_AT"),
            ("ingested_at", "source_available_at", "INGESTED_AT_AFTER_SOURCE_AVAILABLE_AT"),
            (
                "source_available_at",
                "generated_at",
                "SOURCE_AVAILABLE_AT_AFTER_GENERATED_AT",
            ),
            (
                "generated_at",
                "publication_available_at",
                "GENERATED_AT_AFTER_PUBLICATION_AVAILABLE_AT",
            ),
            ("event_time", "feature_cutoff", "EVENT_TIME_AFTER_FEATURE_CUTOFF"),
            ("feature_cutoff", "generated_at", "FEATURE_CUTOFF_AFTER_GENERATED_AT"),
        ):
            if parsed[earlier] > parsed[later]:
                reasons.append(f"SOURCE_RECORD_{reason}")
        if parsed["publication_available_at"] > decision_time:
            reasons.append("SOURCE_RECORD_PUBLICATION_AVAILABLE_AT_AFTER_DECISION_TIME")
        if parsed["source_available_at"] > decision_time:
            reasons.append("SOURCE_RECORD_SOURCE_AVAILABLE_AT_AFTER_DECISION_TIME")
        if parsed["feature_cutoff"] > decision_time:
            reasons.append("SOURCE_RECORD_FEATURE_CUTOFF_AFTER_DECISION_TIME")
        if parsed["generated_at"] > decision_time:
            reasons.append("SOURCE_RECORD_GENERATED_AT_AFTER_DECISION_TIME")
        if parsed["event_time"] > decision_time:
            reasons.append("SOURCE_RECORD_EVENT_TIME_AFTER_DECISION_TIME")
        if parsed["ingested_at"] > decision_time:
            reasons.append("SOURCE_RECORD_INGESTED_AT_AFTER_DECISION_TIME")

    close_value = record.get("candle_close_time")
    close = None if close_value is None else _parse_clock(close_value)
    candle_final = record.get("candle_final")
    if slot.requires_closed_candle:
        if close is None:
            reasons.append("SOURCE_RECORD_CANDLE_CLOSE_TIME_REQUIRED")
        if candle_final is not True:
            reasons.append("SOURCE_RECORD_UNFINISHED_CANDLE")
    elif close_value is not None or candle_final is not None:
        reasons.append("SOURCE_RECORD_NON_CANDLE_FINALITY_FIELDS_FORBIDDEN")
    if close is not None:
        canonical["candle_close_time"] = cast(str, close_value)
        if len(parsed) == len(clock_fields):
            if close > parsed["event_time"]:
                reasons.append("SOURCE_RECORD_CANDLE_CLOSE_AFTER_EVENT_TIME")
            if close >= parsed["source_available_at"]:
                reasons.append("SOURCE_RECORD_CANDLE_CLOSE_NOT_BEFORE_SOURCE_AVAILABLE_AT")
            if close > parsed["feature_cutoff"]:
                reasons.append("SOURCE_RECORD_CANDLE_CLOSE_AFTER_FEATURE_CUTOFF")
            if close >= decision_time:
                reasons.append("SOURCE_RECORD_CANDLE_CLOSE_NOT_BEFORE_DECISION_TIME")
    return tuple(dict.fromkeys(reasons)), canonical


@dataclass(frozen=True, slots=True)
class _PathLookup:
    state: str
    value: object = None


def _lookup(payload: object, path: tuple[str, ...]) -> _PathLookup:
    current = payload
    for part in path:
        if type(current) is not dict:
            return _PathLookup("CONTAINER_TYPE_INVALID")
        mapping = cast(dict[str, object], current)
        if part not in mapping:
            return _PathLookup("ABSENT")
        current = mapping[part]
    if current is None:
        return _PathLookup("NULL")
    if (
        type(current) in (list, dict)
        and len(cast(list[object] | dict[object, object], current)) == 0
    ):
        return _PathLookup("EMPTY_COLLECTION", current)
    return _PathLookup("FOUND", current)


def _apply_transform(
    branch: FeatureResolutionBranchPlanV4,
    values: tuple[object, ...],
) -> tuple[float | None, str | None]:
    if branch.transform_id == TRANSFORM_IDENTITY:
        return _canonical_float32(values[0])
    if branch.transform_id == TRANSFORM_BOOL:
        if type(values[0]) is not bool:
            return None, "VALUE_NOT_EXACT_BOOLEAN"
        return (1.0 if values[0] else 0.0), None
    numeric: list[float] = []
    for value in values:
        parsed, reason = _canonical_float32(value)
        if reason is not None or parsed is None:
            return None, reason or "DEPENDENCY_VALUE_INVALID"
        numeric.append(parsed)
    if len(numeric) != 2:
        return None, "TRANSFORM_DEPENDENCY_ARITY_INVALID"
    first, second = numeric
    if branch.transform_id == TRANSFORM_NONNEGATIVE_DIFFERENCE:
        if first < 0.0 or second < 0.0 or second > first:
            return None, "DEPENDENCY_DOMAIN_INVALID"
        return _canonical_float32(first - second)
    if branch.transform_id in {TRANSFORM_RATIO, TRANSFORM_COMPLEMENT_RATIO}:
        numerator, denominator = first, second
        if numerator < 0.0 or denominator < 0.0 or numerator > denominator:
            return None, "DEPENDENCY_DOMAIN_INVALID"
        if denominator == 0.0:
            if numerator != 0.0:
                return None, "DEPENDENCY_DOMAIN_INVALID"
            ratio = 0.0
        else:
            ratio = numerator / denominator
        if branch.transform_id == TRANSFORM_COMPLEMENT_RATIO:
            ratio = 0.0 if denominator == 0.0 else 1.0 - ratio
        return _canonical_float32(ratio)
    return None, "TRANSFORM_NOT_IMPLEMENTED"


def _base_slot_material(
    slot: FeatureSlotResolutionPlanV4,
    *,
    symbol: str,
    request_timeframe: str,
    source_timeframe: str | None,
    decision_time: str,
    expected_key: str,
    expected_record_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": CANONICAL_FEATURE_VALUE_RESOLVER_V4_SCHEMA_VERSION,
        "evidence_classification": CANONICAL_FEATURE_VALUE_RESOLVER_V4_EVIDENCE_CLASSIFICATION,
        "downstream_status": CANONICAL_FEATURE_VALUE_RESOLVER_V4_DOWNSTREAM_STATUS,
        "resolver_version": CANONICAL_FEATURE_VALUE_RESOLVER_V4_VERSION,
        "feature_resolution_plan_sha256": FEATURE_RESOLUTION_PLAN_V4_SHA256,
        "feature_source_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
        "ordinal": slot.ordinal,
        "feature_name": slot.feature_name,
        "configured_source_label": slot.configured_source_label,
        "requirement_class": slot.requirement_class,
        "plan_status": slot.plan_status,
        "symbol": symbol,
        "request_timeframe": request_timeframe,
        "source_timeframe": source_timeframe,
        "decision_time": decision_time,
        "expected_source_key": expected_key,
        "expected_source_record_id": expected_record_id,
        "expected_payload_schema_version": slot.source_payload_schema_version,
        "resolution_status": None,
        "rejection_reasons": [],
        "resolved_value": None,
        "resolved_value_float32_be_hex": None,
        "selected_source_label": None,
        "selected_source_key": None,
        "selected_source_record_id": None,
        "selected_source_record_sha256": None,
        "selected_payload_schema_version": None,
        "selected_payload_sha256": None,
        "selected_branch_id": None,
        "selected_alias": None,
        "selected_path": None,
        "dependency_paths": [],
        "dependency_leaf_sha256s": [],
        "dependency_root_sha256": None,
        "transform_id": None,
        "transform_version": None,
        "clocks": None,
        "audit_only": True,
        "runtime_wired": False,
        "runtime_source_read_performed": False,
        "caller_supplied_source_record_inspected": False,
        **{field_name: False for field_name in _AUTHORIZATION_FIELDS},
    }


_RESULT_STATE_FIELDS: Final = frozenset(
    {
        "resolution_status",
        "rejection_reasons",
        "resolved_value",
        "resolved_value_float32_be_hex",
        "selected_source_label",
        "selected_source_key",
        "selected_source_record_id",
        "selected_source_record_sha256",
        "selected_payload_schema_version",
        "selected_payload_sha256",
        "selected_branch_id",
        "selected_alias",
        "selected_path",
        "dependency_paths",
        "dependency_leaf_sha256s",
        "dependency_root_sha256",
        "transform_id",
        "transform_version",
        "clocks",
        "caller_supplied_source_record_inspected",
    }
)


def _validate_false_authority(mapping: dict[str, Any]) -> None:
    if mapping.get("audit_only") is not True or mapping.get("runtime_wired") is not False:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_AUTHORITY_INVALID")
    for field_name in _AUTHORIZATION_FIELDS:
        if mapping.get(field_name) is not False:
            _fail("CANONICAL_FEATURE_RESOLVER_V4_AUTHORITY_INVALID")


def _validate_result_clocks(
    clocks: object,
    *,
    decision_time: str,
    requires_closed_candle: bool,
) -> None:
    if type(clocks) is not dict:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_CLOCKS_INVALID")
    values = cast(dict[str, object], clocks)
    expected_fields = {
        "event_time",
        "ingested_at",
        "source_available_at",
        "feature_cutoff",
        "generated_at",
        "publication_available_at",
        "decision_time",
    }
    if requires_closed_candle:
        expected_fields.add("candle_close_time")
    if set(values) != expected_fields or values.get("decision_time") != decision_time:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_CLOCKS_INVALID")
    parsed: dict[str, datetime] = {}
    for name in expected_fields:
        clock = _parse_clock(values.get(name))
        if clock is None:
            _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_CLOCKS_INVALID")
        parsed[name] = clock
    for earlier, later in (
        ("event_time", "ingested_at"),
        ("ingested_at", "source_available_at"),
        ("source_available_at", "generated_at"),
        ("generated_at", "publication_available_at"),
        ("event_time", "feature_cutoff"),
        ("feature_cutoff", "generated_at"),
    ):
        if parsed[earlier] > parsed[later]:
            _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_CLOCK_ORDER_INVALID")
    for name in expected_fields - {"decision_time", "candle_close_time"}:
        if parsed[name] > parsed["decision_time"]:
            _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_CLOCK_ORDER_INVALID")
    if requires_closed_candle:
        close = parsed["candle_close_time"]
        if (
            close > parsed["event_time"]
            or close >= parsed["source_available_at"]
            or close > parsed["feature_cutoff"]
            or close >= parsed["decision_time"]
        ):
            _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_CANDLE_ORDER_INVALID")


def _validate_selected_branch(
    result: dict[str, Any],
    *,
    slot: FeatureSlotResolutionPlanV4,
) -> None:
    branch_id = result.get("selected_branch_id")
    branch = next((item for item in slot.branches if item.branch_id == branch_id), None)
    if branch is None:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_BRANCH_INVALID")
    expected_paths = [list(path) for path in branch.dependency_paths]
    if (
        result.get("selected_alias") != branch.selected_alias
        or result.get("selected_path") != expected_paths[0]
        or result.get("dependency_paths") != expected_paths
        or result.get("transform_id") != branch.transform_id
        or result.get("transform_version") != branch.transform_version
    ):
        _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_BRANCH_INVALID")
    leaf_hashes = result.get("dependency_leaf_sha256s")
    if type(leaf_hashes) is not list or any(
        type(value) is not str or _SHA256_RE.fullmatch(value) is None for value in leaf_hashes
    ):
        _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_DEPENDENCY_BINDING_INVALID")
    root = result.get("dependency_root_sha256")
    if leaf_hashes:
        if len(leaf_hashes) != len(branch.dependency_paths):
            _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_DEPENDENCY_BINDING_INVALID")
        expected_root = _sha256(
            {
                "source_payload_sha256": result.get("selected_payload_sha256"),
                "branch_id": branch.branch_id,
                "transform_id": branch.transform_id,
                "transform_version": branch.transform_version,
                "ordered_dependency_leaf_sha256s": leaf_hashes,
            }
        )
        if root != expected_root:
            _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_DEPENDENCY_BINDING_INVALID")
    elif root is not None:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_DEPENDENCY_BINDING_INVALID")


def _validate_result_semantics(result: dict[str, Any]) -> None:
    ordinal = result.get("ordinal")
    if type(ordinal) is not int or not 0 <= ordinal < len(FEATURE_RESOLUTION_PLAN_V4.slots):
        _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_ORDINAL_INVALID")
    slot = FEATURE_RESOLUTION_PLAN_V4.slots[ordinal]
    symbol, request_timeframe, decision_time, _ = _validate_request(
        result.get("symbol"),
        result.get("request_timeframe"),
        result.get("decision_time"),
    )
    expected_key = materialize_feature_source_key_v4(
        slot,
        symbol=symbol,
        timeframe=request_timeframe,
    )
    source_timeframe = materialize_feature_source_timeframe_v4(
        slot,
        request_timeframe=request_timeframe,
    )
    expected_record_id = canonical_source_record_id_v4(
        source_label=slot.configured_source_label,
        source_key=expected_key,
        symbol=symbol,
        request_timeframe=request_timeframe,
        source_timeframe=source_timeframe,
    )
    expected = _base_slot_material(
        slot,
        symbol=symbol,
        request_timeframe=request_timeframe,
        source_timeframe=source_timeframe,
        decision_time=decision_time,
        expected_key=expected_key,
        expected_record_id=expected_record_id,
    )
    if set(result) != set(expected) | {"result_sha256"}:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_FIELD_SET_INVALID")
    _validate_false_authority(result)
    for name in set(expected) - _RESULT_STATE_FIELDS:
        if result.get(name) != expected[name]:
            _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_INVARIANT_INVALID")
    if result.get("runtime_source_read_performed") is not False:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_AUTHORITY_INVALID")

    status = result.get("resolution_status")
    if type(status) is not str or status not in _RESOLUTION_STATUSES:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_STATUS_INVALID")
    reasons = result.get("rejection_reasons")
    if (
        type(reasons) is not list
        or any(type(reason) is not str or not reason for reason in reasons)
        or len(reasons) != len(set(reasons))
    ):
        _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_REASONS_INVALID")
    if type(result.get("caller_supplied_source_record_inspected")) is not bool:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_INSPECTION_FLAG_INVALID")

    selected = result.get("selected_source_record_id") is not None
    selected_fields = (
        "selected_source_label",
        "selected_source_key",
        "selected_source_record_id",
        "selected_source_record_sha256",
        "selected_payload_schema_version",
        "selected_payload_sha256",
        "selected_branch_id",
        "selected_alias",
        "selected_path",
        "transform_id",
        "transform_version",
        "clocks",
    )
    if selected:
        if (
            result.get("selected_source_label") != slot.configured_source_label
            or result.get("selected_source_key") != expected_key
            or result.get("selected_source_record_id") != expected_record_id
            or result.get("selected_payload_schema_version") != slot.source_payload_schema_version
        ):
            _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_SOURCE_IDENTITY_INVALID")
        for name in ("selected_source_record_sha256", "selected_payload_sha256"):
            value = result.get(name)
            if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
                _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_SOURCE_DIGEST_INVALID")
        _validate_selected_branch(result, slot=slot)
        _validate_result_clocks(
            result.get("clocks"),
            decision_time=decision_time,
            requires_closed_candle=slot.requires_closed_candle,
        )
    else:
        if any(result.get(name) is not None for name in selected_fields):
            _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_PARTIAL_SELECTION_INVALID")
        if result.get("dependency_paths") != []:
            _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_PARTIAL_SELECTION_INVALID")
        if result.get("dependency_leaf_sha256s") != []:
            _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_PARTIAL_SELECTION_INVALID")
        if result.get("dependency_root_sha256") is not None:
            _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_PARTIAL_SELECTION_INVALID")

    value = result.get("resolved_value")
    value_hex = result.get("resolved_value_float32_be_hex")
    if status == RESOLUTION_RESOLVED_MEASURED:
        if not selected or reasons or type(value) is not float:
            _fail("CANONICAL_FEATURE_RESOLVER_V4_RESOLVED_RESULT_INVALID")
        canonical, error = _canonical_float32(value)
        if error is not None or canonical != value or value_hex != _float32_hex(value):
            _fail("CANONICAL_FEATURE_RESOLVER_V4_RESOLVED_RESULT_INVALID")
        if result.get("caller_supplied_source_record_inspected") is not True:
            _fail("CANONICAL_FEATURE_RESOLVER_V4_RESOLVED_RESULT_INVALID")
    elif value is not None or value_hex is not None or not reasons:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_REJECTED_RESULT_INVALID")
    if slot.plan_status != PLAN_RESOLVABLE:
        if status != RESOLUTION_PLAN_UNRESOLVED or selected:
            _fail("CANONICAL_FEATURE_RESOLVER_V4_PLAN_STATUS_RESULT_INVALID")
    elif status == RESOLUTION_PLAN_UNRESOLVED:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_PLAN_STATUS_RESULT_INVALID")


def _validate_result_binding(value: object, expected_digest: object) -> dict[str, Any]:
    result = _parse_result(value)
    if type(expected_digest) is not str or _SHA256_RE.fullmatch(expected_digest) is None:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_BINDING_INVALID")
    if value != _canonical_json(result):
        _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_JSON_NOT_CANONICAL")
    material = {key: item for key, item in result.items() if key != "result_sha256"}
    if _sha256(material) != expected_digest or result.get("result_sha256") != expected_digest:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_RESULT_BINDING_INVALID")
    _validate_result_semantics(result)
    return result


def _validate_audit_binding(value: object, expected_digest: object) -> dict[str, Any]:
    audit = _parse_audit(value)
    if type(expected_digest) is not str or _SHA256_RE.fullmatch(expected_digest) is None:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_AUDIT_BINDING_INVALID")
    if value != _canonical_json(audit):
        _fail("CANONICAL_FEATURE_RESOLVER_V4_AUDIT_JSON_NOT_CANONICAL")
    material = {key: item for key, item in audit.items() if key != "audit_sha256"}
    if _sha256(material) != expected_digest or audit.get("audit_sha256") != expected_digest:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_AUDIT_BINDING_INVALID")
    expected_fields = {
        "schema_version",
        "evidence_classification",
        "downstream_status",
        "resolver_version",
        "feature_resolution_plan_sha256",
        "feature_source_registry_sha256",
        "symbol",
        "request_timeframe",
        "decision_time",
        "slot_count",
        "resolved_measured_slot_count",
        "resolution_status_counts",
        "slot_results",
        "audit_only",
        "runtime_wired",
        "runtime_source_reads_performed",
        "audit_sha256",
        *_AUTHORIZATION_FIELDS,
    }
    if set(audit) != expected_fields:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_AUDIT_FIELD_SET_INVALID")
    if (
        audit.get("schema_version") != CANONICAL_FEATURE_VALUE_RESOLVER_V4_SCHEMA_VERSION
        or audit.get("evidence_classification")
        != CANONICAL_FEATURE_VALUE_RESOLVER_V4_EVIDENCE_CLASSIFICATION
        or audit.get("downstream_status") != CANONICAL_FEATURE_VALUE_RESOLVER_V4_DOWNSTREAM_STATUS
        or audit.get("resolver_version") != CANONICAL_FEATURE_VALUE_RESOLVER_V4_VERSION
        or audit.get("feature_resolution_plan_sha256") != FEATURE_RESOLUTION_PLAN_V4_SHA256
        or audit.get("feature_source_registry_sha256") != FEATURE_SOURCE_REGISTRY_V4_SHA256
    ):
        _fail("CANONICAL_FEATURE_RESOLVER_V4_AUDIT_INVARIANT_INVALID")
    symbol, request_timeframe, decision_time, _ = _validate_request(
        audit.get("symbol"),
        audit.get("request_timeframe"),
        audit.get("decision_time"),
    )
    _validate_false_authority(audit)
    if audit.get("runtime_source_reads_performed") is not False:
        _fail("CANONICAL_FEATURE_RESOLVER_V4_AUTHORITY_INVALID")
    slot_results = audit.get("slot_results")
    if type(slot_results) is not list or len(slot_results) != len(FEATURE_RESOLUTION_PLAN_V4.slots):
        _fail("CANONICAL_FEATURE_RESOLVER_V4_AUDIT_SLOT_COUNT_INVALID")
    slot_count = audit.get("slot_count")
    resolved_count = audit.get("resolved_measured_slot_count")
    status_counts = audit.get("resolution_status_counts")
    if (
        type(slot_count) is not int
        or slot_count < 0
        or type(resolved_count) is not int
        or resolved_count < 0
        or type(status_counts) is not dict
        or any(
            type(status) is not str
            or status not in _RESOLUTION_STATUSES
            or type(count) is not int
            or count <= 0
            for status, count in cast(dict[object, object], status_counts).items()
        )
    ):
        _fail("CANONICAL_FEATURE_RESOLVER_V4_AUDIT_SUMMARY_TYPE_INVALID")
    statuses: dict[str, int] = {}
    for ordinal, result in enumerate(slot_results):
        if type(result) is not dict:
            _fail("CANONICAL_FEATURE_RESOLVER_V4_AUDIT_SLOT_RESULT_INVALID")
        parsed_result = cast(dict[str, Any], result)
        result_digest = parsed_result.get("result_sha256")
        _validate_result_binding(_canonical_json(parsed_result), result_digest)
        if (
            parsed_result.get("ordinal") != ordinal
            or parsed_result.get("symbol") != symbol
            or parsed_result.get("request_timeframe") != request_timeframe
            or parsed_result.get("decision_time") != decision_time
        ):
            _fail("CANONICAL_FEATURE_RESOLVER_V4_AUDIT_SLOT_BINDING_INVALID")
        status = cast(str, parsed_result["resolution_status"])
        statuses[status] = statuses.get(status, 0) + 1
    if (
        slot_count != len(slot_results)
        or resolved_count != statuses.get(RESOLUTION_RESOLVED_MEASURED, 0)
        or status_counts != dict(sorted(statuses.items()))
    ):
        _fail("CANONICAL_FEATURE_RESOLVER_V4_AUDIT_SUMMARY_INVALID")
    return audit


def _freeze_result(material: dict[str, Any]) -> FeatureValueResolutionAuditV4:
    result_sha256 = _sha256(material)
    result = {**material, "result_sha256": result_sha256}
    return FeatureValueResolutionAuditV4(
        result_json=_canonical_json(result),
        result_sha256=result_sha256,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


def _rejected_result(
    material: dict[str, Any],
    *,
    status: str,
    reasons: tuple[str, ...] | list[str],
    inspected: bool = False,
) -> FeatureValueResolutionAuditV4:
    material["resolution_status"] = status
    material["rejection_reasons"] = list(dict.fromkeys(reasons))
    material["caller_supplied_source_record_inspected"] = inspected
    return _freeze_result(material)


def _resolve_slot(
    slot: FeatureSlotResolutionPlanV4,
    *,
    symbol: str,
    request_timeframe: str,
    decision_time_text: str,
    decision_time: datetime,
    source_records: dict[str, dict[str, Any]],
) -> FeatureValueResolutionAuditV4:
    expected_key = materialize_feature_source_key_v4(
        slot,
        symbol=symbol,
        timeframe=request_timeframe,
    )
    source_timeframe = materialize_feature_source_timeframe_v4(
        slot,
        request_timeframe=request_timeframe,
    )
    expected_record_id = canonical_source_record_id_v4(
        source_label=slot.configured_source_label,
        source_key=expected_key,
        symbol=symbol,
        request_timeframe=request_timeframe,
        source_timeframe=source_timeframe,
    )
    material = _base_slot_material(
        slot,
        symbol=symbol,
        request_timeframe=request_timeframe,
        source_timeframe=source_timeframe,
        decision_time=decision_time_text,
        expected_key=expected_key,
        expected_record_id=expected_record_id,
    )
    if slot.plan_status != PLAN_RESOLVABLE:
        return _rejected_result(
            material,
            status=RESOLUTION_PLAN_UNRESOLVED,
            reasons=(cast(str, slot.unresolved_reason),),
        )
    record = source_records.get(expected_record_id)
    if record is None:
        return _rejected_result(
            material,
            status=RESOLUTION_MISSING_SOURCE_RECORD,
            reasons=("EXACT_SOURCE_RECORD_MISSING",),
        )
    material["caller_supplied_source_record_inspected"] = True
    record_reasons, clocks = _record_reasons(
        record,
        slot=slot,
        expected_key=expected_key,
        expected_record_id=expected_record_id,
        symbol=symbol,
        request_timeframe=request_timeframe,
        source_timeframe=source_timeframe,
        decision_time=decision_time,
    )
    if record_reasons:
        return _rejected_result(
            material,
            status=RESOLUTION_SOURCE_RECORD_REJECTED,
            reasons=record_reasons,
            inspected=True,
        )
    payload = record["payload"]
    if type(payload) is list:
        if not payload:
            reason = (
                "AUTHENTICATED_EXACT_EMPTY_WINDOW_RECEIPT_REQUIRED"
                if record.get("absence_receipt") is None
                else "AUTHENTICATED_EMPTY_WINDOW_RECEIPT_VERIFIER_UNWIRED"
            )
            return _rejected_result(
                material,
                status=RESOLUTION_EMPTY_COLLECTION_RECEIPT_REQUIRED,
                reasons=(reason,),
                inspected=True,
            )
        return _rejected_result(
            material,
            status=RESOLUTION_COLLECTION_TRANSFORM_UNWIRED,
            reasons=("EXACT_COLLECTION_SEMANTIC_TRANSFORM_UNWIRED",),
            inspected=True,
        )
    if type(payload) is not dict:
        return _rejected_result(
            material,
            status=RESOLUTION_SOURCE_RECORD_REJECTED,
            reasons=("SOURCE_PAYLOAD_NOT_EXACT_OBJECT_OR_COLLECTION",),
            inspected=True,
        )
    if not payload:
        reason = (
            "AUTHENTICATED_EXACT_EMPTY_WINDOW_RECEIPT_REQUIRED"
            if record.get("absence_receipt") is None
            else "AUTHENTICATED_EMPTY_WINDOW_RECEIPT_VERIFIER_UNWIRED"
        )
        return _rejected_result(
            material,
            status=RESOLUTION_EMPTY_COLLECTION_RECEIPT_REQUIRED,
            reasons=(reason,),
            inspected=True,
        )
    if payload.get("typed_negative") is not None:
        reason = (
            "AUTHENTICATED_TYPED_NEGATIVE_RECEIPT_REQUIRED"
            if record.get("absence_receipt") is None
            else "AUTHENTICATED_TYPED_NEGATIVE_RECEIPT_VERIFIER_UNWIRED"
        )
        return _rejected_result(
            material,
            status=RESOLUTION_TYPED_NEGATIVE_RECEIPT_REQUIRED,
            reasons=(reason,),
            inspected=True,
        )
    if record.get("absence_receipt") is not None:
        return _rejected_result(
            material,
            status=RESOLUTION_SOURCE_RECORD_REJECTED,
            reasons=("ABSENCE_RECEIPT_FOR_POSITIVE_PAYLOAD_FORBIDDEN",),
            inspected=True,
        )

    selected_branch: FeatureResolutionBranchPlanV4 | None = None
    selected_lookups: tuple[_PathLookup, ...] = ()
    malformed_reason: str | None = None
    for branch in slot.branches:
        lookups = tuple(_lookup(payload, path) for path in branch.dependency_paths)
        if any(lookup.state == "CONTAINER_TYPE_INVALID" for lookup in lookups):
            malformed_reason = "SELECTOR_PATH_CONTAINER_TYPE_INVALID"
            break
        if any(lookup.state == "NULL" for lookup in lookups):
            selected_branch = branch
            selected_lookups = lookups
            break
        if any(lookup.state == "EMPTY_COLLECTION" for lookup in lookups):
            selected_branch = branch
            selected_lookups = lookups
            break
        if all(lookup.state == "FOUND" for lookup in lookups):
            selected_branch = branch
            selected_lookups = lookups
            break
    if malformed_reason is not None:
        return _rejected_result(
            material,
            status=RESOLUTION_SOURCE_RECORD_REJECTED,
            reasons=(malformed_reason,),
            inspected=True,
        )
    if selected_branch is None:
        return _rejected_result(
            material,
            status=RESOLUTION_MISSING_PATH,
            reasons=("NO_EXACT_ALLOWED_SELECTOR_PATH_PRESENT",),
            inspected=True,
        )

    payload_sha = cast(str, record["payload_sha256"])
    material.update(
        {
            "selected_source_label": slot.configured_source_label,
            "selected_source_key": expected_key,
            "selected_source_record_id": expected_record_id,
            "selected_source_record_sha256": record["source_record_sha256"],
            "selected_payload_schema_version": slot.source_payload_schema_version,
            "selected_payload_sha256": payload_sha,
            "selected_branch_id": selected_branch.branch_id,
            "selected_alias": selected_branch.selected_alias,
            "selected_path": list(selected_branch.dependency_paths[0]),
            "dependency_paths": [list(path) for path in selected_branch.dependency_paths],
            "transform_id": selected_branch.transform_id,
            "transform_version": selected_branch.transform_version,
            "clocks": {
                **clocks,
                "decision_time": decision_time_text,
                "publication_available_at": record["publication_available_at"],
                "source_available_at": record["source_available_at"],
            },
        }
    )
    if any(lookup.state == "NULL" for lookup in selected_lookups):
        return _rejected_result(
            material,
            status=RESOLUTION_MISSING_NULL,
            reasons=("SELECTED_EXACT_VALUE_IS_NULL",),
            inspected=True,
        )
    if any(lookup.state == "EMPTY_COLLECTION" for lookup in selected_lookups):
        return _rejected_result(
            material,
            status=RESOLUTION_EMPTY_COLLECTION_RECEIPT_REQUIRED,
            reasons=("AUTHENTICATED_EXACT_EMPTY_WINDOW_RECEIPT_REQUIRED",),
            inspected=True,
        )

    values = tuple(lookup.value for lookup in selected_lookups)
    leaf_hashes = tuple(
        _sha256({"path": list(path), "value": lookup.value})
        for path, lookup in zip(selected_branch.dependency_paths, selected_lookups, strict=True)
    )
    dependency_root = _sha256(
        {
            "source_payload_sha256": payload_sha,
            "branch_id": selected_branch.branch_id,
            "transform_id": selected_branch.transform_id,
            "transform_version": selected_branch.transform_version,
            "ordered_dependency_leaf_sha256s": list(leaf_hashes),
        }
    )
    material["dependency_leaf_sha256s"] = list(leaf_hashes)
    material["dependency_root_sha256"] = dependency_root
    value, transform_reason = _apply_transform(selected_branch, values)
    if transform_reason is not None or value is None:
        return _rejected_result(
            material,
            status=RESOLUTION_VALUE_REJECTED,
            reasons=(transform_reason or "TRANSFORM_VALUE_MISSING",),
            inspected=True,
        )
    material["resolution_status"] = RESOLUTION_RESOLVED_MEASURED
    material["resolved_value"] = value
    material["resolved_value_float32_be_hex"] = _float32_hex(value)
    material["rejection_reasons"] = []
    material["caller_supplied_source_record_inspected"] = True
    return _freeze_result(material)


def resolve_canonical_feature_value_v4(
    *,
    ordinal: int,
    symbol: str,
    request_timeframe: str,
    decision_time: str,
    source_records: dict[str, dict[str, Any]],
) -> FeatureValueResolutionAuditV4:
    """Resolve one pinned ordinal without accepting a caller-supplied plan."""

    exact_symbol, exact_timeframe, decision_text, parsed_decision = _validate_request(
        symbol,
        request_timeframe,
        decision_time,
    )
    if type(ordinal) is not int or not 0 <= ordinal < len(FEATURE_RESOLUTION_PLAN_V4.slots):
        _fail("CANONICAL_FEATURE_RESOLVER_V4_ORDINAL_INVALID")
    records = _snapshot_source_records(source_records)
    return _resolve_slot(
        FEATURE_RESOLUTION_PLAN_V4.slots[ordinal],
        symbol=exact_symbol,
        request_timeframe=exact_timeframe,
        decision_time_text=decision_text,
        decision_time=parsed_decision,
        source_records=records,
    )


def resolve_canonical_feature_values_v4(
    *,
    symbol: str,
    request_timeframe: str,
    decision_time: str,
    source_records: dict[str, dict[str, Any]],
) -> CanonicalFeatureResolutionAuditV4:
    """Produce the full ordered 446-slot shadow audit."""

    exact_symbol, exact_timeframe, decision_text, parsed_decision = _validate_request(
        symbol,
        request_timeframe,
        decision_time,
    )
    records = _snapshot_source_records(source_records)
    results = tuple(
        _resolve_slot(
            slot,
            symbol=exact_symbol,
            request_timeframe=exact_timeframe,
            decision_time_text=decision_text,
            decision_time=parsed_decision,
            source_records=records,
        ).result
        for slot in FEATURE_RESOLUTION_PLAN_V4.slots
    )
    statuses: dict[str, int] = {}
    for result in results:
        status = cast(str, result["resolution_status"])
        statuses[status] = statuses.get(status, 0) + 1
    material: dict[str, Any] = {
        "schema_version": CANONICAL_FEATURE_VALUE_RESOLVER_V4_SCHEMA_VERSION,
        "evidence_classification": CANONICAL_FEATURE_VALUE_RESOLVER_V4_EVIDENCE_CLASSIFICATION,
        "downstream_status": CANONICAL_FEATURE_VALUE_RESOLVER_V4_DOWNSTREAM_STATUS,
        "resolver_version": CANONICAL_FEATURE_VALUE_RESOLVER_V4_VERSION,
        "feature_resolution_plan_sha256": FEATURE_RESOLUTION_PLAN_V4_SHA256,
        "feature_source_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
        "symbol": exact_symbol,
        "request_timeframe": exact_timeframe,
        "decision_time": decision_text,
        "slot_count": len(results),
        "resolved_measured_slot_count": statuses.get(RESOLUTION_RESOLVED_MEASURED, 0),
        "resolution_status_counts": dict(sorted(statuses.items())),
        "slot_results": list(results),
        "audit_only": True,
        "runtime_wired": False,
        "runtime_source_reads_performed": False,
        **{field_name: False for field_name in _AUTHORIZATION_FIELDS},
    }
    audit_sha256 = _sha256(material)
    audit = {**material, "audit_sha256": audit_sha256}
    return CanonicalFeatureResolutionAuditV4(
        audit_json=_canonical_json(audit),
        audit_sha256=audit_sha256,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


__all__ = [
    "CANONICAL_FEATURE_VALUE_RESOLVER_V4_DOWNSTREAM_STATUS",
    "CANONICAL_FEATURE_VALUE_RESOLVER_V4_EVIDENCE_CLASSIFICATION",
    "CANONICAL_FEATURE_VALUE_RESOLVER_V4_SCHEMA_VERSION",
    "CANONICAL_FEATURE_VALUE_RESOLVER_V4_VERSION",
    "CanonicalFeatureResolutionAuditV4",
    "CanonicalFeatureValueResolverV4Error",
    "FeatureValueResolutionAuditV4",
    "RESOLUTION_COLLECTION_TRANSFORM_UNWIRED",
    "RESOLUTION_EMPTY_COLLECTION_RECEIPT_REQUIRED",
    "RESOLUTION_MISSING_NULL",
    "RESOLUTION_MISSING_PATH",
    "RESOLUTION_MISSING_SOURCE_RECORD",
    "RESOLUTION_PLAN_UNRESOLVED",
    "RESOLUTION_RESOLVED_MEASURED",
    "RESOLUTION_SOURCE_RECORD_REJECTED",
    "RESOLUTION_TYPED_NEGATIVE_RECEIPT_REQUIRED",
    "RESOLUTION_VALUE_REJECTED",
    "canonical_source_payload_sha256_v4",
    "canonical_source_record_id_v4",
    "canonical_source_record_sha256_v4",
    "resolve_canonical_feature_value_v4",
    "resolve_canonical_feature_values_v4",
]
